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
	ID, Kind, Text              string
	Outgoing                    bool
	Timestamp, Size             int64
	MediaID, Sender             string
	ClientID, AlternateID       string
	downloadName, encryptedName string
}

// CanDownload reports whether a user-facing save action has the addressing
// metadata it needs. The server may still expire or reject a file later.
func (m Message) CanDownload() bool {
	switch m.Kind {
	case "file":
		return m.MediaID != "" && m.Sender != ""
	case "image", "video":
		return m.ID != ""
	}
	return false
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
	FromUserName, ToUserName, Content, FileName, EncryFileName string
	MsgType                                                    int
	CreateTime                                                 int64
	MsgID, NewMsgId, FileSize, MediaId                         wireID
	AppMsgType, ClientMsgId, LocalID                           wireID
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
	id := usableID(r.MsgID)
	alternate := usableID(r.NewMsgId)
	if id == "" {
		id, alternate = alternate, ""
	}
	if alternate == id {
		alternate = ""
	}
	if id == "" {
		return Message{}, false
	}
	clientID := usableID(r.ClientMsgId)
	if clientID == "" {
		clientID = usableID(r.LocalID)
	}
	msg := Message{ID: id, AlternateID: alternate, ClientID: clientID, Kind: "text", Sender: r.FromUserName, Timestamp: r.CreateTime}
	if msg.Timestamp == 0 {
		msg.Timestamp = time.Now().Unix()
	}
	switch r.MsgType {
	case 1:
		msg.Text = plainText(r.Content)
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
		app := parseAppMessage(r.Content)
		subtype := usableID(r.AppMsgType)
		if subtype == "" {
			subtype = strings.TrimSpace(app.Type)
		}
		// Current phones can return all metadata at the JSON level and empty
		// Content. Older messages carry an appattach element in XML instead.
		media := usableID(r.MediaId)
		xmlMedia := usableID(wireID(app.File.ID))
		title := strings.TrimSpace(r.FileName)
		if title == "" {
			title = strings.TrimSpace(app.Title)
		}
		hasFileMetadata := title != "" && (media != "" || xmlMedia != "")
		if subtype == "6" || (subtype == "" && hasFileMetadata) {
			msg.Kind = "file"
			if title == "" {
				title = "file"
			}
			msg.Text = SafeFilename(title)
			msg.downloadName = title
			msg.encryptedName = r.EncryFileName
			msg.MediaID = media
			if msg.MediaID == "" && (app.Type == "" || strings.TrimSpace(app.Type) == "6") {
				msg.MediaID = xmlMedia
			}
			for _, field := range []string{string(r.FileSize), app.File.Length} {
				if size, err := strconv.ParseInt(strings.TrimSpace(field), 10, 64); err == nil && size > 0 {
					msg.Size = size
					break
				}
			}
			return msg, true
		}
		if app.XMLName.Local == "appmsg" || title != "" {
			msg.Text = title + "\n" + app.Description
			return msg, true
		}
	}
	msg.Kind = "unsupported"
	msg.Text = "暂不支持此消息，请在手机微信查看 / View this message on your phone"
	return msg, true
}

func usableID(id wireID) string {
	s := strings.TrimSpace(string(id))
	if s == "0" {
		return ""
	}
	return s
}

func parseAppMessage(content string) appMessage {
	content = unwrapAppXML(content)
	if !strings.HasPrefix(content, "<") {
		return appMessage{}
	}
	app := readAppXML(content)
	if app.XMLName.Local == "" && breaks.MatchString(content) {
		// Some sync responses insert HTML breaks between XML tags. Parse
		// ordinary XML first to preserve a literal <br> inside a CDATA title.
		app = readAppXML(breaks.ReplaceAllString(content, "\n"))
	}
	return app
}

func unwrapAppXML(content string) string {
	content = strings.TrimSpace(strings.TrimPrefix(content, "\ufeff"))
	// Decode HTML wrappers before XML, so entities inside an actual XML
	// filename or CDATA section are interpreted only by the XML parser.
	for n := 0; n < 2 && strings.HasPrefix(content, "&"); n++ {
		content = strings.TrimSpace(html.UnescapeString(content))
	}
	return content
}

func readAppXML(content string) appMessage {
	var app appMessage
	if err := xml.Unmarshal([]byte(content), &app); err == nil {
		return app
	}
	var msg struct {
		XMLName xml.Name    `xml:"msg"`
		App     *appMessage `xml:"appmsg"`
		Text    string      `xml:",chardata"`
	}
	if err := xml.Unmarshal([]byte(content), &msg); err != nil {
		return appMessage{}
	}
	if msg.App != nil {
		return *msg.App
	}
	// A message envelope can contain its appmsg document as escaped text.
	// Only accept a direct appmsg root, not a quoted or nested forwarded file.
	inner := unwrapAppXML(msg.Text)
	if strings.HasPrefix(inner, "<") && xml.Unmarshal([]byte(inner), &app) == nil {
		return app
	}
	return appMessage{}
}

type sendReceipt struct{ local, server string }

// A phone sending to its own filehelper uses this same WeChat user name.
// Attribute an echo to this PC only with an ID issued by this client or a
// matching server acknowledgement. Never use the filename, text or time.
func (c *Client) markLocalEcho(msg *Message, raw rawMessage, s *session) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	localID := usableID(raw.LocalID)
	toHelper := raw.FromUserName == s.username && raw.ToUserName == "filehelper"
	for _, sent := range c.sent {
		if sent.local == "" {
			continue
		}
		matchesServer := sent.server != "" && (msg.ID == sent.server || msg.AlternateID == sent.server)
		matchesLocal := toHelper && (msg.ClientID == sent.local || localID == sent.local || msg.ID == sent.local || msg.AlternateID == sent.local)
		if matchesServer || matchesLocal {
			msg.Outgoing = true
			msg.ClientID = sent.local
			return
		}
	}
}

func (c *Client) send(ctx context.Context, s *session, kind int, endpoint, content string) (sendReceipt, error) {
	id := strconv.FormatInt(c.nextID(), 10)
	receipt := sendReceipt{local: id}
	c.mu.Lock()
	slot := c.nextSent
	c.sent[slot] = receipt
	c.nextSent = (c.nextSent + 1) % len(c.sent)
	c.mu.Unlock()
	r, err := c.api(ctx, s, endpoint, map[string]any{"BaseRequest": s.base(), "Scene": 0, "Msg": map[string]any{
		"Type": kind, "Content": content, "FromUserName": s.username, "ToUserName": "filehelper",
		"LocalID": id, "ClientMsgId": id,
	}}, url.Values{"fun": {"async"}, "f": {"json"}})
	if err != nil {
		return sendReceipt{}, err
	}
	receipt.server = usableID(r.MsgID)
	if receipt.server == "" {
		receipt.server = id
	}
	c.mu.Lock()
	if c.sent[slot].local == id {
		c.sent[slot] = receipt
	}
	c.mu.Unlock()
	return receipt, nil
}
func (c *Client) SendText(ctx context.Context, text string) (Message, error) {
	if !utf8.ValidString(text) || strings.TrimSpace(text) == "" || utf8.RuneCountInString(text) > 10000 {
		return Message{}, errors.New("文字长度需为 1–10000 字符 / Text must contain 1–10000 characters")
	}
	s, err := c.current()
	if err != nil {
		return Message{}, err
	}
	receipt, err := c.send(ctx, s, 1, "webwxsendmsg", text)
	if err != nil {
		return Message{}, err
	}
	return Message{ID: receipt.server, ClientID: receipt.local, Kind: "text", Text: text, Outgoing: true, Timestamp: time.Now().Unix(), Sender: s.username}, nil
}
