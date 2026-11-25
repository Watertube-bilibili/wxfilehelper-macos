// SPDX-License-Identifier: AGPL-3.0-only

// Package desktop manages two independent File Transfer sessions for native frontends.
package desktop

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/Watertube-bilibili/wxfilehelper-desktop/native/internal/wechat"
)

const Version = "1.2.2"

const (
	maxAccounts = 2
	maxQueue    = 100
	maxHistory  = 300
)

type Account struct {
	ID                  uint64
	DraftEpoch          uint64
	Name, Status, Error string
	QR                  []byte
	SignedIn, Busy      bool
	Downloading         bool
	Messages            []wechat.Message
	Files               []QueuedFile
	Sent, Total         int64
}

type QueuedFile struct {
	Path, Name string
	Size       int64
}

type Snapshot struct {
	Revision, Active uint64
	Accounts         []Account
	Update           *Update
	UpdateStatus     string
}

type transferClient interface {
	CreateQR(context.Context) ([]byte, error)
	PollLogin(context.Context) (string, error)
	Identity() (string, string)
	Sync(context.Context) ([]wechat.Message, error)
	SendText(context.Context, string) (wechat.Message, error)
	SendFile(context.Context, string, func(int64, int64)) (wechat.Message, error)
	Download(context.Context, wechat.Message, string) error
	Close()
}

type session struct {
	ctx    context.Context
	cancel context.CancelFunc
	client transferClient
}

func (s *session) close() {
	s.cancel()
	s.client.Close()
}

type account struct {
	Account
	session  *session
	username string
	stop     bool
}

type Controller struct {
	mu              sync.Mutex
	ctx             context.Context
	cancel          context.CancelFunc
	closed          bool
	newClient       func() transferClient
	accounts        []*account
	active, nextID  uint64
	revision        uint64
	update          *Update
	updateStatus    string
	updateScheduler bool
}

var (
	errClosed = errors.New("程序已经退出 / The app has closed")
	errTab    = errors.New("找不到此会话 / Account tab not found")
	errLogin  = errors.New("请先扫码登录 / Scan to sign in first")
	errBusy   = errors.New("正在发送，请稍候 / A transfer is in progress")
)

func New() *Controller {
	ctx, cancel := context.WithCancel(context.Background())
	c := &Controller{
		ctx: ctx, cancel: cancel, updateStatus: "idle",
		newClient: func() transferClient { return wechat.New() },
	}
	_, _ = c.AddAccount()
	return c
}

func (c *Controller) Snapshot() Snapshot {
	c.mu.Lock()
	defer c.mu.Unlock()
	s := Snapshot{Active: c.active, Revision: c.revision, UpdateStatus: c.updateStatus}
	if c.update != nil {
		u := *c.update
		s.Update = &u
	}
	s.Accounts = make([]Account, 0, len(c.accounts))
	for _, a := range c.accounts {
		view := a.Account
		view.QR = slices.Clone(view.QR)
		view.Files = slices.Clone(view.Files)
		view.Messages = slices.Clone(view.Messages)
		s.Accounts = append(s.Accounts, view)
	}
	return s
}

func (c *Controller) AddAccount() (uint64, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return 0, errClosed
	}
	if len(c.accounts) >= maxAccounts {
		return 0, errors.New("最多同时打开两个账号 / Up to two account tabs are supported")
	}
	c.nextID++
	c.active = c.nextID
	c.accounts = append(c.accounts, &account{Account: Account{ID: c.nextID, Status: "idle"}})
	c.revision++
	return c.active, nil
}

func (c *Controller) SetActive(id uint64) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.find(id) == nil {
		return errTab
	}
	if c.active != id {
		c.active = id
		c.revision++
	}
	return nil
}

func (c *Controller) RemoveAccount(id uint64) error {
	c.mu.Lock()
	if len(c.accounts) < 2 {
		c.mu.Unlock()
		return errors.New("请保留一个会话 / Keep at least one account tab")
	}
	for index, a := range c.accounts {
		if a.ID != id {
			continue
		}
		c.accounts = slices.Delete(c.accounts, index, index+1)
		if c.active == id {
			c.active = c.accounts[0].ID
		}
		c.revision++
		s := a.session
		a.session = nil
		c.mu.Unlock()
		if s != nil {
			s.close()
		}
		return nil
	}
	c.mu.Unlock()
	return errTab
}

func (c *Controller) Start(id uint64) error {
	c.mu.Lock()
	a := c.find(id)
	if a == nil {
		c.mu.Unlock()
		return errTab
	}
	if a.SignedIn {
		c.mu.Unlock()
		return errors.New("请先退出当前账号 / Sign out of this account first")
	}
	previous := a.session
	ctx, cancel := context.WithCancel(c.ctx)
	s := &session{ctx: ctx, cancel: cancel, client: c.newClient()}
	*a = account{Account: Account{ID: id, DraftEpoch: a.DraftEpoch, Status: "connecting"}, session: s}
	c.revision++
	c.mu.Unlock()
	if previous != nil {
		previous.close()
	}
	go c.connect(id, s)
	return nil
}

func (c *Controller) SignOut(id uint64) error {
	c.mu.Lock()
	a := c.find(id)
	if a == nil {
		c.mu.Unlock()
		return errTab
	}
	s := a.session
	*a = account{Account: Account{ID: id, DraftEpoch: a.DraftEpoch + 1, Status: "idle"}}
	c.revision++
	c.mu.Unlock()
	if s != nil {
		s.close()
	}
	return nil
}

func (c *Controller) Close() {
	c.mu.Lock()
	if c.closed {
		c.mu.Unlock()
		return
	}
	c.closed = true
	c.cancel()
	accounts := c.accounts
	c.accounts = nil
	c.active = 0
	c.revision++
	c.mu.Unlock()
	for _, a := range accounts {
		if a.session != nil {
			a.session.close()
		}
	}
}

// find must be called with the controller locked.
func (c *Controller) find(id uint64) *account {
	for _, a := range c.accounts {
		if a.ID == id {
			return a
		}
	}
	return nil
}

func (c *Controller) change(id uint64, s *session, change func(*account)) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	a := c.find(id)
	if a == nil || a.session != s {
		return false
	}
	change(a)
	c.revision++
	return true
}

func (c *Controller) connect(id uint64, s *session) {
	qr, err := s.client.CreateQR(s.ctx)
	if err != nil {
		c.expire(id, s, err)
		return
	}
	if !c.change(id, s, func(a *account) { a.QR, a.Status = qr, "scan" }) {
		return
	}
	for {
		state, err := s.client.PollLogin(s.ctx)
		if err != nil {
			c.expire(id, s, err)
			return
		}
		switch state {
		case "confirmed":
			if c.authorize(id, s) {
				c.sync(id, s)
			}
			return
		case "scanned":
			c.change(id, s, func(a *account) { a.Status = "scanned" })
		case "waiting":
		case "expired":
			c.expire(id, s, errors.New("二维码已过期，请刷新 / QR code expired. Refresh to try again."))
			return
		default:
			c.expire(id, s, errors.New("无法识别登录状态 / Unrecognized sign-in state"))
			return
		}
		if !pause(s.ctx, 400*time.Millisecond) {
			return
		}
	}
}

func (c *Controller) authorize(id uint64, s *session) bool {
	user, name := s.client.Identity()
	c.mu.Lock()
	a := c.find(id)
	if a == nil || a.session != s {
		c.mu.Unlock()
		return false
	}
	for _, other := range c.accounts {
		if other != a && other.SignedIn && other.username == user {
			c.mu.Unlock()
			c.expire(id, s, errors.New("此微信账号已在另一个标签登录 / This WeChat account is already signed in in another tab"))
			return false
		}
	}
	a.username = user
	a.Name, a.Status, a.SignedIn, a.QR, a.Error = name, "online", true, nil, ""
	c.revision++
	c.mu.Unlock()
	return true
}

func (c *Controller) expire(id uint64, s *session, err error) {
	if c.change(id, s, func(a *account) {
		*a = account{Account: Account{ID: id, DraftEpoch: a.DraftEpoch + 1, Status: "expired", Error: err.Error()}}
	}) {
		s.close()
	}
}

func (c *Controller) sync(id uint64, s *session) {
	hadError := false
	for s.ctx.Err() == nil {
		messages, err := s.client.Sync(s.ctx)
		if errors.Is(err, wechat.ErrSessionExpired) {
			c.expire(id, s, err)
			return
		}
		if err != nil {
			if !hadError {
				c.change(id, s, func(a *account) { a.Status = "reconnecting" })
			}
			hadError = true
			if !pause(s.ctx, 3*time.Second) {
				return
			}
			continue
		}
		if hadError || len(messages) != 0 {
			if !c.change(id, s, func(a *account) {
				a.Status = "online"
				for _, message := range messages {
					appendMessage(a, message, true)
				}
			}) {
				return
			}
		}
		hadError = false
		if !pause(s.ctx, 300*time.Millisecond) {
			return
		}
	}
}

func pause(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

func hasServerID(m wechat.Message, id string) bool {
	return id != "" && (id == m.ID || id == m.AlternateID)
}

func appendMessage(a *account, message wechat.Message, fromSync bool) {
	if message.ID == "" {
		return
	}
	for i := range a.Messages {
		old := &a.Messages[i]
		if !hasServerID(*old, message.ID) && !hasServerID(*old, message.AlternateID) &&
			(message.ClientID == "" || message.ClientID != old.ClientID) {
			continue
		}
		// Echoes and send receipts may arrive in either order. A sync record
		// can have a newer media token or an encrypted download name.
		other := message
		if old.Kind == "unsupported" || (!old.CanDownload() && message.CanDownload()) ||
			(fromSync && message.CanDownload()) {
			other = *old
			*old = message
		}
		if old.ClientID == "" {
			old.ClientID = other.ClientID
		}
		if old.AlternateID == "" {
			if other.ID != old.ID {
				old.AlternateID = other.ID
			} else {
				old.AlternateID = other.AlternateID
			}
		}
		old.Outgoing = old.Outgoing || other.Outgoing
		return
	}
	a.Messages = append(a.Messages, message)
	if len(a.Messages) > maxHistory {
		a.Messages = slices.Delete(a.Messages, 0, len(a.Messages)-maxHistory)
	}
}

func (c *Controller) Queue(id uint64, paths []string) error {
	files := make([]QueuedFile, 0, min(len(paths), maxQueue))
	for _, name := range paths {
		if len(files) >= maxQueue {
			return errors.New("待发送列表最多 100 个文件 / Up to 100 files in the queue")
		}
		absolute, err := filepath.Abs(name)
		if err != nil {
			return errors.New("无法读取文件路径 / Could not read the file path")
		}
		info, err := os.Stat(absolute)
		if err != nil || !info.Mode().IsRegular() {
			return errors.New("无法读取本地文件 / Could not read the local file")
		}
		if info.Size() < 1 || info.Size() > wechat.MaxFileSize {
			return errors.New("文件大小须为 1 字节至 25 MiB / Files must be between 1 byte and 25 MiB")
		}
		files = append(files, QueuedFile{Path: absolute, Name: info.Name(), Size: info.Size()})
	}
	return c.editQueue(id, func(a *account) error {
		if len(a.Files)+len(files) > maxQueue {
			return errors.New("待发送列表最多 100 个文件 / Up to 100 files in the queue")
		}
		a.Files = append(a.Files, files...)
		return nil
	})
}

func (c *Controller) RemoveFile(id uint64, index int) error {
	return c.editQueue(id, func(a *account) error {
		if index < 0 || index >= len(a.Files) {
			return errors.New("找不到此文件 / Queued file not found")
		}
		a.Files = slices.Delete(a.Files, index, index+1)
		return nil
	})
}

func (c *Controller) ClearFiles(id uint64) error {
	return c.editQueue(id, func(a *account) error {
		a.Files = nil
		return nil
	})
}

func (c *Controller) editQueue(id uint64, edit func(*account) error) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	a := c.find(id)
	if a == nil {
		return errTab
	}
	if !a.SignedIn {
		return errLogin
	}
	if a.Busy {
		return errBusy
	}
	if err := edit(a); err != nil {
		return err
	}
	a.Error = ""
	c.revision++
	return nil
}

func (c *Controller) Send(id uint64, text string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	a := c.find(id)
	if a == nil {
		return errTab
	}
	if !a.SignedIn || a.session == nil {
		return errLogin
	}
	if a.Busy {
		return errBusy
	}
	if strings.TrimSpace(text) == "" {
		text = ""
	}
	if text == "" && len(a.Files) == 0 {
		return errors.New("请输入文字或添加文件 / Enter text or add a file")
	}
	a.Busy, a.stop, a.Error, a.Sent, a.Total = true, false, "", 0, 0
	c.revision++
	go c.send(id, a.session, text, slices.Clone(a.Files))
	return nil
}

func (c *Controller) StopSending(id uint64) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	a := c.find(id)
	if a == nil {
		return errTab
	}
	a.stop = true
	return nil
}

func (c *Controller) send(id uint64, s *session, text string, files []QueuedFile) {
	var failure error
	defer func() {
		if errors.Is(failure, wechat.ErrSessionExpired) {
			c.expire(id, s, failure)
			return
		}
		c.change(id, s, func(a *account) {
			a.Busy, a.Sent, a.Total = false, 0, 0
			if failure != nil {
				a.Error = failure.Error()
			}
		})
	}()
	if text != "" {
		message, err := s.client.SendText(s.ctx, text)
		if err != nil {
			failure = err
			return
		}
		if !c.change(id, s, func(a *account) { appendMessage(a, message, false) }) {
			return
		}
	}
	for _, file := range files {
		var stopped bool
		if !c.change(id, s, func(a *account) {
			stopped = a.stop
			if !stopped {
				a.Sent, a.Total = 0, file.Size
			}
		}) || stopped {
			return
		}
		message, err := s.client.SendFile(s.ctx, file.Path, func(sent, total int64) {
			c.change(id, s, func(a *account) { a.Sent, a.Total = sent, total })
		})
		if err != nil {
			failure = err
			return
		}
		if !c.change(id, s, func(a *account) {
			appendMessage(a, message, false)
			a.Files = slices.Delete(a.Files, 0, 1)
		}) {
			return
		}
	}
}

func (c *Controller) Download(id uint64, messageID, target string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	a := c.find(id)
	if a == nil {
		return errTab
	}
	if !a.SignedIn || a.session == nil {
		return errLogin
	}
	if a.Downloading {
		return errors.New("正在保存文件，请稍候 / A file is already being saved")
	}
	for _, message := range a.Messages {
		if hasServerID(message, messageID) && message.CanDownload() {
			a.Downloading, a.Error = true, ""
			c.revision++
			go c.download(id, a.session, message, target)
			return nil
		}
	}
	return errors.New("找不到可下载的附件 / Downloadable attachment not found")
}

func (c *Controller) download(id uint64, s *session, message wechat.Message, target string) {
	err := s.client.Download(s.ctx, message, target)
	if errors.Is(err, wechat.ErrSessionExpired) {
		c.expire(id, s, err)
		return
	}
	c.change(id, s, func(a *account) {
		a.Downloading = false
		if err != nil {
			a.Error = err.Error()
		}
	})
}
