// Package wechat implements the published HTTPS filehelper flow used by
// ItChat and WXFileHelper. See THIRD_PARTY_NOTICES.md for attribution.
// SPDX-License-Identifier: AGPL-3.0-only
package wechat

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const root = "/cgi-bin/mmwebwx-bin/"
const initialHost = "szfilehelper.weixin.qq.com"

var regions = map[string]struct{ login, file string }{
	"filehelper.weixin.qq.com":   {"login.wx.qq.com", "file.wx.qq.com"},
	"szfilehelper.weixin.qq.com": {"login.wx2.qq.com", "file.wx2.qq.com"},
	"cmfilehelper.weixin.qq.com": {"login.wx8.qq.com", "file.wx8.qq.com"},
}

var (
	ErrSessionExpired = errors.New("登录已失效，请重新扫码 / Session expired; scan again")
	errResponse       = errors.New("微信返回的数据格式异常 / Unexpected service response")
	errHost           = errors.New("微信返回了不可信的地址 / Untrusted service address")
	errNetwork        = errors.New("无法连接微信，请检查网络 / Could not reach WeChat")
)

type syncPair struct{ Key, Val int64 }
type syncKey struct {
	Count int
	List  []syncPair
}

func (k syncKey) encode() string {
	items := make([]string, len(k.List))
	for i, pair := range k.List {
		items[i] = fmt.Sprintf("%d_%d", pair.Key, pair.Val)
	}
	return strings.Join(items, "|")
}

type session struct {
	host, device, sid, skey, uin, ticket, username, nickname string
	number                                                   int64
}

func (s session) base() map[string]any {
	return map[string]any{"Uin": s.number, "Sid": s.sid, "Skey": s.skey, "DeviceID": s.device}
}

type Client struct {
	http          *http.Client
	jar           *accountJar
	lifetime      context.Context
	cancel        context.CancelFunc
	device        string
	loginMu       sync.Mutex // serializes QR creation and polling
	uuid          string
	scanned       bool
	syncMu        sync.Mutex // one synchronization cursor per account
	mu            sync.RWMutex
	s             *session
	key, checkKey syncKey
	sequence      atomic.Int64
	sent          [320]sendReceipt
	nextSent      int
}

// Discard all cookies at sign-out, including Path/Domain variations and late
// responses to requests that were in flight when the tab closed.
type accountJar struct {
	mu  sync.RWMutex
	jar *cookiejar.Jar
}

func (j *accountJar) Cookies(u *url.URL) []*http.Cookie {
	j.mu.RLock()
	defer j.mu.RUnlock()
	if j.jar == nil {
		return nil
	}
	return j.jar.Cookies(u)
}
func (j *accountJar) SetCookies(u *url.URL, cookies []*http.Cookie) {
	j.mu.RLock()
	defer j.mu.RUnlock()
	if j.jar != nil {
		j.jar.SetCookies(u, cookies)
	}
}

func New() *Client {
	jar, _ := cookiejar.New(nil)
	store := &accountJar{jar: jar}
	ctx, cancel := context.WithCancel(context.Background())
	var digits [15]byte
	// A device ID is an opaque service identifier, never a login credential.
	if _, err := rand.Read(digits[:]); err != nil {
		panic(err)
	}
	for i := range digits {
		digits[i] = '0' + digits[i]%10
	}
	return &Client{http: &http.Client{
		Jar: store, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}, jar: store, lifetime: ctx, cancel: cancel, device: "e" + string(digits[:])}
}

func (c *Client) Close() {
	c.cancel()
	c.mu.Lock()
	c.s = nil
	c.key, c.checkKey = syncKey{}, syncKey{}
	clear(c.sent[:])
	c.mu.Unlock()
	c.loginMu.Lock()
	c.uuid = ""
	c.scanned = false
	c.loginMu.Unlock()
	c.jar.mu.Lock()
	c.jar.jar = nil
	c.jar.mu.Unlock()
}

func (c *Client) Identity() (id, name string) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.s != nil {
		return c.s.uin, c.s.nickname
	}
	return "", ""
}

func (c *Client) current() (*session, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.lifetime.Err() != nil {
		return nil, context.Canceled
	}
	if c.s == nil {
		return nil, ErrSessionExpired
	}
	return c.s, nil
}

func serviceURL(host, path, endpoint string) *url.URL {
	return &url.URL{Scheme: "https", Host: host, Path: path + endpoint}
}

func validateURL(u *url.URL, login bool) bool {
	if u == nil || u.Scheme != "https" || u.User != nil || u.Fragment != "" || u.Opaque != "" {
		return false
	}
	host := u.Hostname()
	if u.Host != host && u.Host != host+":443" {
		return false
	}
	if _, ok := regions[host]; ok {
		return !login || (u.EscapedPath() == root+"webwxnewloginpage")
	}
	if login {
		return false
	}
	for _, r := range regions {
		if host == r.login || host == r.file {
			return true
		}
	}
	return false
}

type responseBody struct {
	io.ReadCloser
	finish func()
}

func (b responseBody) Close() error {
	err := b.ReadCloser.Close()
	b.finish()
	return err
}

func (c *Client) request(parent context.Context, method string, u *url.URL, origin string, body io.Reader, headers http.Header, timeout time.Duration) (*http.Response, error) {
	if !validateURL(u, false) {
		return nil, errHost
	}
	if err := c.lifetime.Err(); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	stop := context.AfterFunc(c.lifetime, cancel)
	finish := func() { stop(); cancel() }
	req, err := http.NewRequestWithContext(ctx, method, u.String(), body)
	if err != nil {
		finish()
		return nil, errHost
	}
	for key, vals := range headers {
		for _, v := range vals {
			req.Header.Add(key, v)
		}
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")
	req.Header.Set("mmweb_appid", "wx_webfilehelper")
	req.Header.Set("Origin", "https://"+origin)
	req.Header.Set("Referer", "https://"+origin+"/")
	req.Header.Set("Accept", "*/*")
	res, err := c.http.Do(req)
	if err != nil {
		ctxErr := ctx.Err()
		finish()
		if ctxErr != nil {
			return nil, ctxErr
		}
		return nil, errNetwork // net/url errors contain login tickets
	}
	if res.StatusCode != http.StatusOK && res.StatusCode != http.StatusPartialContent {
		res.Body.Close()
		finish()
		return nil, fmt.Errorf("微信服务返回 HTTP %d / Service request failed", res.StatusCode)
	}
	res.Body = responseBody{res.Body, finish}
	return res, nil
}

func readBounded(r io.Reader, max int64) ([]byte, error) {
	b, err := io.ReadAll(io.LimitReader(r, max+1))
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return nil, context.Canceled
		}
		return nil, errNetwork
	}
	if int64(len(b)) > max {
		return nil, errResponse
	}
	return b, nil
}
func (c *Client) get(ctx context.Context, u *url.URL, origin string, query url.Values, max int64) ([]byte, error) {
	if query != nil {
		u.RawQuery = query.Encode()
	}
	r, err := c.request(ctx, "GET", u, origin, nil, nil, 55*time.Second)
	if err != nil {
		return nil, err
	}
	defer r.Body.Close()
	if r.StatusCode != 200 {
		return nil, errResponse
	}
	return readBounded(r.Body, max)
}

// wireID preserves identifiers even when a service region returns a JSON
// number instead of a string (some exceed JavaScript's integer precision).
type wireID string

func (id *wireID) UnmarshalJSON(data []byte) error {
	if len(data) > 0 && data[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		*id = wireID(s)
		return nil
	}
	if string(data) == "null" {
		*id = ""
		return nil
	}
	if _, err := strconv.ParseUint(string(data), 10, 64); err != nil {
		return err
	}
	*id = wireID(data)
	return nil
}

type apiResponse struct {
	BaseResponse          struct{ Ret *int }
	User                  struct{ UserName, NickName string }
	SyncKey, SyncCheckKey syncKey
	AddMsgList            []rawMessage
	ContinueFlag          int
	MsgID, MediaId        wireID
}

func checkRet(code int) error {
	switch code {
	case 0:
		return nil
	case 1100, 1101, 1102, 1205:
		return ErrSessionExpired
	}
	return fmt.Errorf("微信未接受请求（%d）/ WeChat rejected request", code)
}
func readAPI(r *http.Response) (apiResponse, error) {
	defer r.Body.Close()
	var result apiResponse
	b, err := readBounded(r.Body, 16<<20)
	if err != nil {
		return result, err
	}
	if r.StatusCode != 200 || json.Unmarshal(b, &result) != nil || result.BaseResponse.Ret == nil {
		return result, errResponse
	}
	return result, checkRet(*result.BaseResponse.Ret)
}
func (c *Client) api(ctx context.Context, s *session, endpoint string, data any, query url.Values) (apiResponse, error) {
	if query == nil {
		query = url.Values{}
	}
	query.Set("lang", "zh_CN")
	query.Set("pass_ticket", s.ticket)
	u := serviceURL(s.host, root, endpoint)
	u.RawQuery = query.Encode()
	b, err := json.Marshal(data)
	if err != nil {
		return apiResponse{}, errResponse
	}
	r, err := c.request(ctx, "POST", u, s.host, bytes.NewReader(b), http.Header{"Content-Type": {"application/json; charset=UTF-8"}}, 55*time.Second)
	if err != nil {
		return apiResponse{}, err
	}
	return readAPI(r)
}

func (c *Client) nextID() int64 {
	for {
		last := c.sequence.Load()
		next := time.Now().UnixNano()
		if next <= last {
			next = last + 1
		}
		if c.sequence.CompareAndSwap(last, next) {
			return next
		}
	}
}
