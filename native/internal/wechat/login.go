// SPDX-License-Identifier: AGPL-3.0-only
package wechat

import (
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"html"
	"net/url"
	"regexp"
	"strconv"
	"time"
)

var (
	qrID        = regexp.MustCompile(`window\.QRLogin\.uuid\s*=\s*"([A-Za-z0-9_=-]+)"`)
	loginCode   = regexp.MustCompile(`window\.code\s*=\s*([0-9]+)`)
	redirectURI = regexp.MustCompile(`window\.redirect_uri\s*=\s*"([^"]+)"`)
	syncStatus  = regexp.MustCompile(`retcode\s*:\s*"([0-9]+)"\s*,\s*selector\s*:\s*"([0-9]+)"`)
)

func milliseconds() string { return strconv.FormatInt(time.Now().UnixMilli(), 10) }

func (c *Client) CreateQR(ctx context.Context) ([]byte, error) {
	c.loginMu.Lock()
	defer c.loginMu.Unlock()
	if id, _ := c.Identity(); id != "" {
		return nil, errors.New("已登录 / Already signed in")
	}
	c.uuid = ""
	c.scanned = false
	login := regions[initialHost].login
	// jslogin takes a URL-escaped redirect_uri inside the encoded query.
	dest := serviceURL(initialHost, root, "webwxnewloginpage")
	body, err := c.get(ctx, serviceURL(login, "/", "jslogin"), initialHost, url.Values{
		"appid": {"wx_webfilehelper"}, "redirect_uri": {url.QueryEscape(dest.String())},
		"fun": {"new"}, "lang": {"zh_CN"}, "_": {milliseconds()},
	}, 64<<10)
	if err != nil {
		return nil, err
	}
	m := qrID.FindSubmatch(body)
	if m == nil {
		return nil, errors.New("无法获取登录二维码 / Could not obtain a login code")
	}
	uuid := string(m[1])
	image, err := c.get(ctx, serviceURL(login, "/qrcode/", uuid), initialHost, nil, 2<<20)
	if err != nil {
		return nil, err
	}
	if len(image) == 0 {
		return nil, errResponse
	}
	c.uuid = uuid
	return image, nil
}

func (c *Client) PollLogin(ctx context.Context) (string, error) {
	c.loginMu.Lock()
	defer c.loginMu.Unlock()
	if err := c.lifetime.Err(); err != nil {
		return "", err
	}
	if id, _ := c.Identity(); id != "" {
		return "confirmed", nil
	}
	if c.uuid == "" {
		return "expired", nil
	}
	tip := "1"
	if c.scanned {
		tip = "0"
	}
	body, err := c.get(ctx, serviceURL(regions[initialHost].login, root, "login"), initialHost, url.Values{
		"loginicon": {"true"}, "uuid": {c.uuid}, "tip": {tip}, "appid": {"wx_webfilehelper"}, "_": {milliseconds()},
	}, 2<<20)
	if err != nil {
		return "", err
	}
	m := loginCode.FindSubmatch(body)
	if m == nil {
		return "", errResponse
	}
	switch string(m[1]) {
	case "408":
		if c.scanned {
			return "scanned", nil
		}
		return "waiting", nil
	case "201":
		c.scanned = true
		return "scanned", nil
	case "400", "500":
		c.uuid = ""
		return "expired", nil
	case "200":
		m = redirectURI.FindSubmatch(body)
		if m == nil {
			return "", errResponse
		}
		if err := c.finishLogin(ctx, html.UnescapeString(string(m[1]))); err != nil {
			return "", err
		}
		c.uuid = ""
		return "confirmed", nil
	default:
		return "", fmt.Errorf("当前无法登录（%s）/ Login unavailable", string(m[1]))
	}
}

func (c *Client) finishLogin(ctx context.Context, dest string) error {
	u, err := url.Parse(dest)
	if err != nil || !validateURL(u, true) {
		return errHost
	}
	values := u.Query()
	values.Set("fun", "new")
	values.Set("version", "v2")
	s := &session{host: u.Hostname(), device: c.device}
	body, err := c.get(ctx, u, s.host, values, 128<<10)
	if err != nil {
		return err
	}
	var ticket struct {
		XMLName xml.Name `xml:"error"`
		Ret     string   `xml:"ret"`
		Skey    string   `xml:"skey"`
		Sid     string   `xml:"wxsid"`
		Uin     string   `xml:"wxuin"`
		Ticket  string   `xml:"pass_ticket"`
	}
	if xml.Unmarshal(body, &ticket) != nil {
		return errResponse
	}
	if ticket.Ret != "" && ticket.Ret != "0" {
		return errors.New("微信未接受本次登录 / Login not accepted")
	}
	s.skey, s.sid, s.uin, s.ticket = ticket.Skey, ticket.Sid, ticket.Uin, ticket.Ticket
	s.number, err = strconv.ParseInt(s.uin, 10, 64)
	if err != nil || s.number <= 0 || s.skey == "" || s.sid == "" || s.ticket == "" {
		return errResponse
	}
	result, err := c.api(ctx, s, "webwxinit", map[string]any{"BaseRequest": s.base()}, url.Values{"r": {strconv.FormatInt(time.Now().Unix(), 10)}})
	if err != nil {
		return err
	}
	s.username, s.nickname = result.User.UserName, plainText(result.User.NickName)
	if s.username == "" || len(result.SyncKey.List) == 0 {
		return errResponse
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.lifetime.Err(); err != nil {
		return err
	}
	c.s = s
	c.key = result.SyncKey
	c.checkKey = result.SyncCheckKey
	if len(c.checkKey.List) == 0 {
		c.checkKey = c.key
	}
	return nil
}

func (c *Client) Sync(ctx context.Context) ([]Message, error) {
	c.syncMu.Lock()
	defer c.syncMu.Unlock()
	s, err := c.current()
	if err != nil {
		return nil, err
	}
	c.mu.RLock()
	key, check := c.key, c.checkKey
	c.mu.RUnlock()
	body, err := c.get(ctx, serviceURL(s.host, root, "synccheck"), s.host, url.Values{
		"r": {milliseconds()}, "skey": {s.skey}, "sid": {s.sid}, "uin": {s.uin},
		"deviceid": {s.device}, "synckey": {check.encode()}, "mmweb_appid": {"wx_webfilehelper"},
	}, 64<<10)
	if err != nil {
		return nil, err
	}
	m := syncStatus.FindSubmatch(body)
	if m == nil {
		return nil, errResponse
	}
	code, err := strconv.Atoi(string(m[1]))
	if err != nil {
		return nil, errResponse
	}
	if err = checkRet(code); err != nil {
		return nil, err
	}
	if string(m[2]) == "0" {
		return nil, nil
	}
	var messages []Message
	for page := 0; page < 20; page++ {
		r, err := c.api(ctx, s, "webwxsync", map[string]any{"BaseRequest": s.base(), "SyncKey": key, "rr": ^time.Now().Unix()},
			url.Values{"sid": {s.sid}, "skey": {s.skey}})
		if err != nil {
			return nil, err
		}
		if len(r.SyncKey.List) > 0 {
			key = r.SyncKey
		}
		check = r.SyncCheckKey
		if len(check.List) == 0 {
			check = key
		}
		for _, raw := range r.AddMsgList {
			if msg, ok := raw.message(); ok {
				c.markLocalEcho(&msg, raw, s)
				messages = append(messages, msg)
			}
		}
		if r.ContinueFlag == 0 {
			break
		}
	}
	// Commit the cursor only after the whole batch is ready for delivery.
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.s != s {
		return nil, context.Canceled
	}
	c.key, c.checkKey = key, check
	return messages, nil
}
