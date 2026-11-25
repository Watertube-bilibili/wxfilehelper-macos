package desktop

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/Watertube-bilibili/wxfilehelper-desktop/native/internal/wechat"
)

type mockSession struct {
	id     string
	sends  chan string
	finish chan error
}

func (s *mockSession) CreateQR(context.Context) ([]byte, error)  { return []byte(s.id), nil }
func (s *mockSession) PollLogin(context.Context) (string, error) { return "confirmed", nil }
func (s *mockSession) Identity() (string, string)                { return s.id, s.id }
func (s *mockSession) Close()                                    {}
func (s *mockSession) Sync(ctx context.Context) ([]wechat.Message, error) {
	<-ctx.Done()
	return nil, ctx.Err()
}
func (s *mockSession) SendText(_ context.Context, text string) (wechat.Message, error) {
	return wechat.Message{ID: s.id + "-text", Text: text, Kind: "text", Outgoing: true}, nil
}
func (s *mockSession) SendFile(ctx context.Context, path string, progress func(int64, int64)) (wechat.Message, error) {
	if s.sends != nil {
		select {
		case s.sends <- path:
		case <-ctx.Done():
			return wechat.Message{}, ctx.Err()
		}
	}
	if s.finish != nil {
		select {
		case err := <-s.finish:
			if err != nil {
				return wechat.Message{}, err
			}
		case <-ctx.Done():
			return wechat.Message{}, ctx.Err()
		}
	}
	progress(1, 1)
	return wechat.Message{ID: path, Text: filepath.Base(path), Outgoing: true, Kind: "file"}, nil
}
func (s *mockSession) Download(_ context.Context, message wechat.Message, target string) error {
	return os.WriteFile(target, []byte(message.Text), 0600)
}

func awaitView(t *testing.T, c *Controller, id uint64, check func(Account) bool) Account {
	t.Helper()
	deadline := time.NewTimer(5 * time.Second)
	defer deadline.Stop()
	tick := time.NewTicker(5 * time.Millisecond)
	defer tick.Stop()
	for {
		for _, a := range c.Snapshot().Accounts {
			if a.ID == id && check(a) {
				return a
			}
		}
		select {
		case <-deadline.C:
			t.Fatalf("account %d did not reach the expected state", id)
		case <-tick.C:
		}
	}
}

func newTestController(t *testing.T, clients ...transferClient) *Controller {
	t.Helper()
	c := New()
	c.newClient = func() transferClient {
		client := clients[0]
		clients = clients[1:]
		return client
	}
	t.Cleanup(c.Close)
	return c
}

func TestDualSessionsAndFailedQueue(t *testing.T) {
	first := &mockSession{id: "first", sends: make(chan string, 1), finish: make(chan error, 1)}
	second := &mockSession{id: "second"}
	c := newTestController(t, first, second)
	one := c.Snapshot().Active
	two, err := c.AddAccount()
	if err != nil || two == one {
		t.Fatalf("second tab: %d %v", two, err)
	}
	if _, err := c.AddAccount(); err == nil {
		t.Fatal("third tab was created")
	}
	for _, id := range []uint64{one, two} {
		if err := c.Start(id); err != nil {
			t.Fatal(err)
		}
		awaitView(t, c, id, func(a Account) bool { return a.SignedIn })
	}
	dir := t.TempDir()
	paths := []string{filepath.Join(dir, "第一.txt"), filepath.Join(dir, "second.txt")}
	for _, p := range paths {
		if err := os.WriteFile(p, []byte{1}, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.Queue(one, paths); err != nil {
		t.Fatal(err)
	}
	if err := c.Send(one, ""); err != nil {
		t.Fatal(err)
	}
	select {
	case got := <-first.sends:
		if got != paths[0] {
			t.Fatalf("queue order: %s", got)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("queued file was not sent")
	}
	if err := c.Send(two, "second tab is independent"); err != nil {
		t.Fatal(err)
	}
	awaitView(t, c, two, func(a Account) bool {
		return len(a.Messages) == 1 && len(a.Files) == 0 && !a.Busy
	})
	first.finish <- errors.New("transfer error")
	awaitView(t, c, one, func(a Account) bool {
		return len(a.Files) == 2 && !a.Busy && a.Error == "transfer error"
	})
	if err := c.SignOut(one); err != nil {
		t.Fatal(err)
	}
	awaitView(t, c, one, func(a Account) bool {
		return !a.SignedIn && a.DraftEpoch == 1 && len(a.Messages) == 0 && len(a.Files) == 0
	})
	awaitView(t, c, two, func(a Account) bool { return a.SignedIn })
}

func TestDuplicateAccountRejectedAndCloseIsSafe(t *testing.T) {
	c := newTestController(t, &mockSession{id: "same"}, &mockSession{id: "same"})
	one := c.Snapshot().Active
	two, _ := c.AddAccount()
	if err := c.Start(one); err != nil {
		t.Fatal(err)
	}
	awaitView(t, c, one, func(a Account) bool { return a.SignedIn })
	if err := c.Start(two); err != nil {
		t.Fatal(err)
	}
	awaitView(t, c, two, func(a Account) bool { return a.Status == "expired" && !a.SignedIn })

	var group sync.WaitGroup
	group.Go(c.Close)
	group.Go(c.Close)
	group.Wait()
	if _, err := c.AddAccount(); !errors.Is(err, errClosed) {
		t.Fatal("closed controller accepted a new tab")
	}
}

func TestPhoneAttachmentAndLocalEchoStayDistinct(t *testing.T) {
	receipt := wechat.Message{ID: "server", ClientID: "client1", Outgoing: true, Kind: "file", Text: "slides.pptx", MediaID: "uploaded", Sender: "owner"}
	echo := wechat.Message{ID: "sync", AlternateID: "server", Kind: "file", Text: "slides.pptx", MediaID: "refreshed", Sender: "owner"}
	for _, echoFirst := range []bool{false, true} {
		a := &account{}
		if echoFirst {
			appendMessage(a, echo, true)
			appendMessage(a, receipt, false)
		} else {
			appendMessage(a, receipt, false)
			appendMessage(a, echo, true)
		}
		incoming := echo
		incoming.ID, incoming.AlternateID = "other", ""
		appendMessage(a, incoming, true)
		if len(a.Messages) != 2 || !a.Messages[0].Outgoing || a.Messages[0].MediaID != "refreshed" ||
			a.Messages[0].ClientID != "client1" || a.Messages[1].Outgoing || !a.Messages[1].CanDownload() {
			t.Fatal("receipt and echo must merge, and the phone's separate upload must stay incoming")
		}
	}
}

func TestRuntimeUpdateChecksKeepLastReleaseWhileOffline(t *testing.T) {
	c := New()
	defer c.Close()
	if !c.beginUpdateCheck() || c.beginUpdateCheck() {
		t.Fatal("concurrent release checks should be coalesced")
	}
	known := &Update{Version: "v9.0.0", URL: "https://example.test/release"}
	c.finishUpdateCheck(func(context.Context) (*Update, error) { return known, nil })
	if !c.beginUpdateCheck() || c.finishUpdateCheck(func(context.Context) (*Update, error) {
		return nil, errors.New("offline")
	}) {
		t.Fatal("failed runtime check should be eligible for an earlier retry")
	}
	if s := c.Snapshot(); s.UpdateStatus != "failed" || s.Update == nil || *s.Update != *known {
		t.Fatal("offline check erased a previously discovered release")
	}
}
