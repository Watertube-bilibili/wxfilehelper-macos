// SPDX-License-Identifier: AGPL-3.0-only
package wechat

import (
	"bytes"
	"context"
	"crypto/md5" // WeChat's upload checksum; not used for authentication.
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"errors"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const MaxFileSize = 25 * 1024 * 1024
const chunkSize = 512 * 1024

var errChanged = errors.New("文件在发送时发生变化，请保存后重试 / File changed while sending")
var errIncomplete = errors.New("下载不完整，请重试 / Incomplete download")
var wholeRange = regexp.MustCompile(`^bytes 0-([0-9]+)/([0-9]+)$`)

func (c *Client) dataTicket(s *session, endpoint string) string {
	for _, host := range []string{regions[s.host].file, s.host} {
		for _, cookie := range c.jar.Cookies(serviceURL(host, root, endpoint)) {
			if cookie.Name == "webwx_data_ticket" && cookie.Value != "" {
				return cookie.Value
			}
		}
	}
	return ""
}

func (c *Client) SendFile(ctx context.Context, path string, progress func(sent, total int64)) (Message, error) {
	s, err := c.current()
	if err != nil {
		return Message{}, err
	}
	ticket := c.dataTicket(s, "webwxuploadmedia")
	if ticket == "" {
		return Message{}, ErrSessionExpired
	}
	src, err := os.Open(path)
	if err != nil {
		return Message{}, err
	}
	defer src.Close()
	initial, err := src.Stat()
	if err != nil {
		return Message{}, err
	}
	size := initial.Size()
	if !initial.Mode().IsRegular() || size < 1 || size > MaxFileSize {
		return Message{}, errors.New("本版支持 1 字节至 25 MiB 的普通文件 / Supported file size: 1 byte to 25 MiB")
	}
	nChunks := (size + chunkSize - 1) / chunkSize
	digest := md5.New()
	buf := make([]byte, chunkSize)
	for offset := int64(0); offset < size; {
		if err = ctx.Err(); err != nil {
			return Message{}, err
		}
		if err = c.lifetime.Err(); err != nil {
			return Message{}, err
		}
		block := buf[:min(int64(len(buf)), size-offset)]
		if _, err = io.ReadFull(src, block); err != nil {
			return Message{}, errChanged
		}
		digest.Write(block)
		offset += int64(len(block))
	}
	if _, err = src.Seek(0, io.SeekStart); err != nil {
		return Message{}, err
	}
	sum := hex.EncodeToString(digest.Sum(nil))
	digest.Reset()
	name := filepath.Base(path)
	request, err := json.Marshal(map[string]any{"UploadType": 2, "BaseRequest": s.base(), "ClientMediaId": time.Now().UnixMilli(),
		"TotalLen": size, "StartPos": 0, "DataLen": size, "MediaType": 4, "FromUserName": s.username,
		"ToUserName": "filehelper", "FileMd5": sum})
	if err != nil {
		return Message{}, errResponse
	}
	mimeType, _, _ := mime.ParseMediaType(mime.TypeByExtension(filepath.Ext(name)))
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}
	fields := map[string]string{"id": "WU_FILE_0", "name": name, "type": mimeType, "lastModifiedDate": initial.ModTime().UTC().Format("Mon Jan 02 2006 15:04:05 GMT+0000"),
		"size": strconv.FormatInt(size, 10), "mediatype": "doc", "uploadmediarequest": string(request), "webwx_data_ticket": ticket, "pass_ticket": s.ticket}
	if nChunks > 1 {
		fields["chunks"] = strconv.FormatInt(nChunks, 10)
	}
	var media string
	for i := int64(0); i < nChunks; i++ {
		block := buf[:min(int64(len(buf)), size-i*chunkSize)]
		if _, err = io.ReadFull(src, block); err != nil {
			return Message{}, errChanged
		}
		if !unchanged(src, initial) {
			return Message{}, errChanged
		}
		digest.Write(block)
		if nChunks > 1 {
			fields["chunk"] = strconv.FormatInt(i, 10)
		}
		media, err = c.uploadChunk(ctx, s, name, mimeType, fields, block)
		if err != nil {
			return Message{}, err
		}
		if progress != nil && i+1 < nChunks {
			progress((i+1)*chunkSize, size)
		}
	}
	if !unchanged(src, initial) || hex.EncodeToString(digest.Sum(nil)) != sum {
		return Message{}, errChanged
	}
	if media == "" {
		return Message{}, errors.New("上传未返回文件标识 / Upload did not return a file ID")
	}
	body, err := fileXML(name, size, media)
	if err != nil {
		return Message{}, err
	}
	receipt, err := c.send(ctx, s, 6, "webwxsendappmsg", body)
	if err != nil {
		return Message{}, err
	}
	if progress != nil {
		progress(size, size)
	}
	return Message{ID: receipt.server, ClientID: receipt.local, Kind: "file", Text: name, Outgoing: true, Timestamp: time.Now().Unix(), Size: size, MediaID: media, Sender: s.username}, nil
}

func unchanged(f *os.File, initial os.FileInfo) bool {
	current, err := f.Stat()
	return err == nil && current.Size() == initial.Size() && current.ModTime().Equal(initial.ModTime())
}

func (c *Client) uploadChunk(ctx context.Context, s *session, name, mimeType string, fields map[string]string, block []byte) (string, error) {
	var b bytes.Buffer
	m := multipart.NewWriter(&b)
	for k, v := range fields {
		if err := m.WriteField(k, v); err != nil {
			return "", err
		}
	}
	h := textproto.MIMEHeader{}
	h.Set("Content-Type", mimeType)
	h.Set("Content-Disposition", multipart.FileContentDisposition("filename", name))
	part, err := m.CreatePart(h)
	if err != nil {
		return "", err
	}
	if _, err = part.Write(block); err != nil {
		return "", err
	}
	if err = m.Close(); err != nil {
		return "", err
	}
	u := serviceURL(regions[s.host].file, root, "webwxuploadmedia")
	u.RawQuery = "f=json"
	r, err := c.request(ctx, "POST", u, s.host, &b, http.Header{"Content-Type": {m.FormDataContentType()}}, 2*time.Minute)
	if err != nil {
		return "", err
	}
	result, err := readAPI(r)
	return string(result.MediaId), err
}

func (c *Client) Download(ctx context.Context, msg Message, target string) error {
	s, err := c.current()
	if err != nil {
		return err
	}
	host := s.host
	q := url.Values{"skey": {s.skey}, "pass_ticket": {s.ticket}}
	h := http.Header{"Accept-Encoding": {"identity"}}
	var endpoint string
	switch msg.Kind {
	case "file":
		if !msg.CanDownload() {
			return errors.New("文件已不可用，请从手机重新发送 / File no longer available")
		}
		host = regions[s.host].file
		endpoint = "webwxgetmedia"
		q.Set("sender", msg.Sender)
		q.Set("mediaid", msg.MediaID)
		if msg.encryptedName != "" {
			q.Set("encryfilename", msg.encryptedName)
		} else {
			name := msg.downloadName
			if name == "" {
				name = msg.Text
			}
			q.Set("filename", name)
		}
		q.Set("fromuser", s.uin)
		ticket := c.dataTicket(s, endpoint)
		if ticket == "" {
			return errors.New("缺少文件下载授权，请重新扫码 / Scan again to authorize downloading files")
		}
		q.Set("webwx_data_ticket", ticket)
		q.Set("sid", s.sid)
		q.Set("mmweb_appid", "wx_webfilehelper")
	case "image", "video", "voice":
		endpoint = map[string]string{"image": "webwxgetmsgimg", "video": "webwxgetvideo", "voice": "webwxgetvoice"}[msg.Kind]
		q.Set("MsgID", msg.ID)
		if msg.Kind == "video" {
			h.Set("Range", "bytes=0-")
		}
	default:
		return errors.New("此消息不支持下载 / This message cannot be downloaded")
	}
	u := serviceURL(host, root, endpoint)
	u.RawQuery = q.Encode()
	r, err := c.request(ctx, "GET", u, s.host, nil, h, 30*time.Minute)
	if err != nil {
		return err
	}
	defer r.Body.Close()
	if encoding := r.Header.Get("Content-Encoding"); encoding != "" && !strings.EqualFold(encoding, "identity") {
		return errResponse
	}
	expected := r.ContentLength
	if r.StatusCode == 206 {
		m := wholeRange.FindStringSubmatch(r.Header.Get("Content-Range"))
		if m == nil {
			return errIncomplete
		}
		last, e1 := strconv.ParseInt(m[1], 10, 64)
		total, e2 := strconv.ParseInt(m[2], 10, 64)
		if e1 != nil || e2 != nil || total <= 0 || last != total-1 || (expected >= 0 && expected != total) {
			return errIncomplete
		}
		expected = total
	}
	// A small complete JSON/XML protocol error can also be sent with HTTP 200.
	// Only inspect complete small bodies, so user HTML, XML and JSON survive.
	head, err := io.ReadAll(io.LimitReader(r.Body, 64<<10))
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errIncomplete
	}
	n := len(head)
	if n == 0 {
		return errIncomplete
	}
	if n < 64<<10 && serviceError(head) {
		return errors.New("文件已过期或微信拒绝下载 / File expired or service rejected download")
	}
	if msg.Kind == "file" && msg.Size > 0 {
		if expected >= 0 && expected != msg.Size {
			return errIncomplete
		}
		expected = msg.Size
	}
	f, err := os.CreateTemp(filepath.Dir(target), ".wxfilehelper-*.part")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, err = f.Write(head); err != nil {
		return err
	}
	written, err := io.Copy(f, r.Body)
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errIncomplete
	}
	if expected >= 0 && written+int64(n) != expected {
		return errIncomplete
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = ctx.Err(); err != nil {
		return err
	}
	if err = c.lifetime.Err(); err != nil {
		return err
	}
	return os.Rename(f.Name(), target)
}

func serviceError(b []byte) bool {
	b = bytes.TrimSpace(b)
	if len(b) == 0 {
		return false
	}
	switch b[0] {
	case '{':
		var r apiResponse
		return json.Unmarshal(b, &r) == nil && r.BaseResponse.Ret != nil && *r.BaseResponse.Ret != 0
	case '<':
		var r struct {
			XMLName xml.Name `xml:"error"`
			Ret     *int     `xml:"ret"`
		}
		return xml.Unmarshal(b, &r) == nil && r.Ret != nil && *r.Ret != 0
	}
	return false
}
