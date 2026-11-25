// SPDX-License-Identifier: AGPL-3.0-only
package wechat

import (
	"context"
	"encoding/xml"
	"errors"
	"html"
	"net/url"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type Message struct {
	ID, Kind, Text  string
	Outgoing        bool
	Timestamp, Size int64
	MediaID, Sender string
}

var breaks = regexp.MustCompile(`(?i)<br\s*/?>`)
var reserved = regexp.MustCompile(`(?i)^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$`)

func plainText(s string) string { return html.UnescapeString(breaks.ReplaceAllString(s, "\n")) }

func SafeFilename(name string) string {
	if i := strings.LastIndexAny(name, `/\`); i >= 0 {
		name = name[i+1:]
	}
	name = strings.Trim(strings.Map(func(r rune) rune {
		if r < 32 || strings.ContainsRune(`<>:"/\|?*`, r) {
			return '_'
		}
		return r
	}, name), " .")
	for len(name) > 240 {
		_, n := utf8.DecodeLastRuneInString(name)
		name = name[:len(name)-n]
	}
	name = strings.TrimRight(name, " .")
	if name == "" {
		return "download"
	}
	if base, _, _ := strings.Cut(name, "."); reserved.MatchString(strings.TrimRight(base, " ")) {
		return "_" + name
	}
	return name
}

type rawMessage struct {
	FromUserName, ToUserName, Content, FileName string
	MsgType                                     int
	CreateTime                                  int64
	MsgID, NewMsgId, FileSize, MediaId          wireID
}
type attachment struct {
	Length    string `xml:"totallen"`
	ID        string `xml:"attachid"`
	Extension string `xml:"fileext"`
}
type appMessage struct {
	XMLName     xml.Name   `xml:"appmsg"`
	AppID       string     `xml:"appid,attr"`
	SDK         string     `xml:"sdkver,attr"`
	Title       string     `xml:"title"`
	Description string     `xml:"des"`
	Action      string     `xml:"action"`
	Type        string     `xml:"type"`
	Content     string     `xml:"content"`
	URL         string     `xml:"url"`
	LowURL      string     `xml:"lowurl"`
	File        attachment `xml:"appattach"`
	ExtInfo     string     `xml:"extinfo"`
}

func fileXML(name string, size int64, media string) (string, error) {
	b, err := xml.Marshal(appMessage{AppID: "wxeb7ec651dd0aefa9", Title: name, Type: "6",
		File: attachment{Length: strconv.FormatInt(size, 10), ID: media, Extension: strings.TrimPrefix(filepath.Ext(name), ".")}})
	return string(b), err
}
func (r rawMessage) message() (Message, bool) {
	if r.FromUserName != "filehelper" && r.ToUserName != "filehelper" {
		return Message{}, false
	}
	id := r.NewMsgId
	if id == "" || id == "0" {
		id = r.MsgID
	}
	if id == "" {
		return Message{}, false
	}
	msg := Message{ID: string(id), Kind: "text", Text: plainText(r.Content), Sender: r.FromUserName, Timestamp: r.CreateTime}
	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().Unix()
	}
	switch r.MsgType {
	case 1:
		return msg, true
	case 51, 10000, 10002:
		return Message{}, false
	case 3, 43, 62, 34:
		kind, ext := "image", ".jpg"
		if r.MsgType == 34 {
			kind, ext = "voice", ".silk"
		} else if r.MsgType != 3 {
			kind, ext = "video", ".mp4"
		}
		msg.Kind = kind
		msg.Text = SafeFilename(kind + "-" + msg.ID + ext)
		return msg, true
	case 49:
		content := strings.TrimSpace(r.Content)
		if !strings.HasPrefix(content, "<") {
			content = html.UnescapeString(content)
		}
		var app appMessage
		if xml.Unmarshal([]byte(content), &app) != nil {
			var envelope struct {
				App *appMessage `xml:"appmsg"`
			}
			if xml.Unmarshal([]byte(content), &envelope) != nil || envelope.App == nil {
				break
			}
			app = *envelope.App
		}
		title := app.Title
		if title == "" {
			title = r.FileName
		}
		if title == "" {
			title = "file"
		}
		if app.Type != "6" {
			msg.Text = title + "\n" + app.Description
			return msg, true
		}
		size := app.File.Length
		if size == "" {
			size = string(r.FileSize)
		}
		if size != "" {
			n, err := strconv.ParseInt(size, 10, 64)
			if err != nil {
				break
			}
			if n > 0 {
				msg.Size = n
			}
		}
		msg.Kind = "file"
		msg.Text = SafeFilename(title)
		msg.MediaID = app.File.ID
		if msg.MediaID == "" {
			msg.MediaID = string(r.MediaId)
		}
		return msg, true
	}
	msg.Kind = "unsupported"
	msg.Text = "暂不支持此消息，请在手机微信查看 / View this message on your phone"
	return msg, true
}

func (c *Client) send(ctx context.Context, s *session, kind int, endpoint, content string) (string, error) {
	id := strconv.FormatInt(c.nextID(), 10)
	r, err := c.api(ctx, s, endpoint, map[string]any{"BaseRequest": s.base(), "Scene": 0, "Msg": map[string]any{
		"Type": kind, "Content": content, "FromUserName": s.username, "ToUserName": "filehelper",
		"LocalID": id, "ClientMsgId": id,
	}}, url.Values{"fun": {"async"}, "f": {"json"}})
	if err != nil {
		return "", err
	}
	if r.MsgID != "" {
		id = string(r.MsgID)
	}
	return id, nil
}
func (c *Client) SendText(ctx context.Context, text string) (Message, error) {
	if !utf8.ValidString(text) || strings.TrimSpace(text) == "" || utf8.RuneCountInString(text) > 10000 {
		return Message{}, errors.New("文字长度需为 1–10000 字符 / Text must contain 1–10000 characters")
	}
	s, err := c.current()
	if err != nil {
		return Message{}, err
	}
	id, err := c.send(ctx, s, 1, "webwxsendmsg", text)
	if err != nil {
		return Message{}, err
	}
	return Message{ID: id, Kind: "text", Text: text, Outgoing: true, Timestamp: time.Now().Unix(), Sender: s.username}, nil
}
