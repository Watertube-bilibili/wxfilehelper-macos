// SPDX-License-Identifier: AGPL-3.0-only
package wechat

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// No captured messages or credentials. Exercise an Office archive through the
// same sync -> message -> download entry points used for a real phone transfer.
func TestPhonePowerPointSyncAndDownload(t *testing.T) {
	var b bytes.Buffer
	z := zip.NewWriter(&b)
	for name, body := range map[string]string{
		"[Content_Types].xml":  `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>`,
		"_rels/.rels":          `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>`,
		"ppt/presentation.xml": `<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>`,
	} {
		w, err := z.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = io.WriteString(w, body); err != nil {
			t.Fatal(err)
		}
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	c := online(t)
	const name = "周四课件 & optics.pptx"
	const encryptedName = "lesson%2Epptx+A&B"
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case root + "synccheck":
			return respond(`window.synccheck={retcode:"0",selector:"2"}`), nil
		case root + "webwxsync":
			raw := map[string]any{"FromUserName": "@one", "ToUserName": "filehelper", "MsgType": 49, "AppMsgType": 6,
				"MsgId": "845000000000000001", "NewMsgId": 845000000000000001, "Content": "",
				"FileName": name, "FileSize": fmt.Sprint(b.Len()), "MediaId": "token+/=&", "EncryFileName": encryptedName}
			js, e := json.Marshal(map[string]any{"BaseResponse": map[string]int{"Ret": 0}, "AddMsgList": []any{raw}})
			if e != nil {
				t.Fatal(e)
			}
			return respond(string(js)), nil
		case root + "webwxgetmedia":
			if r.URL.Host != regions[initialHost].file {
				t.Fatal("incorrect file region")
			}
			q := r.URL.Query()
			for key, want := range map[string]string{"mediaid": "token+/=&", "sender": "@one", "encryfilename": encryptedName, "fromuser": "123", "webwx_data_ticket": "data", "pass_ticket": "ticket", "sid": "sid", "mmweb_appid": "wx_webfilehelper"} {
				if q.Get(key) != want {
					t.Errorf("incorrect %s query field", key)
				}
			}
			return respond(b.String()), nil
		default:
			t.Fatalf("unexpected endpoint %s", r.URL.Path)
			return nil, nil
		}
	})
	msgs, err := c.Sync(t.Context())
	if err != nil || len(msgs) != 1 {
		t.Fatalf("sync returned %d messages, err=%v", len(msgs), err)
	}
	m := msgs[0]
	if m.Kind != "file" || m.Text != name || m.Size != int64(b.Len()) || m.MediaID != "token+/=&" || m.Outgoing {
		t.Fatalf("attachment not recognized: kind=%q name=%q size=%d", m.Kind, m.Text, m.Size)
	}
	dst := filepath.Join(t.TempDir(), name)
	if err = c.Download(t.Context(), m, dst); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(dst)
	if err != nil || !bytes.Equal(got, b.Bytes()) {
		t.Fatal("download altered Office archive", err)
	}
}

func TestAttachmentsAndOtherAppMessages(t *testing.T) {
	for _, tc := range []struct {
		name, fields, kind, title, media string
		size                             int64
	}{
		{"sparse metadata", `"AppMsgType":"6","FileName":"slides.pptx","FileSize":42,"MediaId":"t","Content":"<msg/>"`, "file", "slides.pptx", "t", 42},
		{"malformed content", `"AppMsgType":6,"FileName":"notes.docx","MediaId":"t","Content":"<msg><bad"`, "file", "notes.docx", "t", 0},
		{"unavailable metadata", `"AppMsgType":6,"FileName":"讲义.pptx","EncryFileName":"name.pptx","Content":""`, "file", "讲义.pptx", "", 0},
		{"double escaped XML", `"Content":"&amp;lt;msg&amp;gt;&amp;lt;appmsg&amp;gt;&amp;lt;type&amp;gt;6&amp;lt;/type&amp;gt;&amp;lt;title&amp;gt;A &amp;amp;amp; B.pptx&amp;lt;/title&amp;gt;&amp;lt;appattach&amp;gt;&amp;lt;attachid&amp;gt;t&amp;lt;/attachid&amp;gt;&amp;lt;/appattach&amp;gt;&amp;lt;/appmsg&amp;gt;&amp;lt;/msg&amp;gt;"`, "file", "A & B.pptx", "t", 0},
		{"escaped appmsg inside envelope", `"Content":"<msg>&lt;appmsg&gt;&lt;type&gt;6&lt;/type&gt;&lt;title&gt;A &amp;amp; B.pptx&lt;/title&gt;&lt;appattach&gt;&lt;attachid&gt;t&lt;/attachid&gt;&lt;/appattach&gt;&lt;/appmsg&gt;</msg>"`, "file", "A & B.pptx", "t", 0},
		{"preserve CDATA", `"Content":"<msg><appmsg><type>6</type><title><![CDATA[A<br>B &amp; C.pdf]]></title><appattach><attachid>t</attachid></appattach></appmsg></msg>"`, "file", "A_br_B &amp; C.pdf", "t", 0},
		{"HTML line break between XML tags", `"Content":"<msg><BR><appmsg><type>6</type><title>lesson.pptx</title><appattach><attachid>t</attachid></appattach></appmsg></msg>"`, "file", "lesson.pptx", "t", 0},
		{"top-level ID beats XML placeholder", `"AppMsgType":6,"FileName":"课件.pptx","MediaId":"authorized","FileSize":42,"Content":"<appmsg><title>presentation</title><type>6</type><appattach><attachid>legacy</attachid><totallen>not supplied</totallen></appattach></appmsg>"`, "file", "课件.pptx", "authorized", 42},
		{"ordinary link titled pptx", `"AppMsgType":5,"Content":"<appmsg><type>5</type><title>shared.pptx</title><des>URL</des></appmsg>"`, "text", "shared.pptx\nURL", "", 0},
		{"quoted attachment inside forward", `"AppMsgType":19,"Content":"<msg><appmsg><type>19</type><title>History</title><recorditem><appmsg><type>6</type><appattach><attachid>unrelated</attachid></appattach></appmsg></recorditem></appmsg></msg>"`, "text", "History\n", "", 0},
		{"local message ID is not media ID", `"AppMsgType":6,"FileName":"only-name.pptx","Content":""`, "file", "only-name.pptx", "", 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var raw rawMessage
			if err := json.Unmarshal([]byte(`{"MsgType":49,"MsgId":"42","ToUserName":"filehelper","FromUserName":"@one",`+tc.fields+"}"), &raw); err != nil {
				t.Fatal(err)
			}
			m, ok := raw.message()
			if !ok || m.Kind != tc.kind || m.Text != tc.title || m.MediaID != tc.media || m.Size != tc.size {
				t.Errorf("got kind=%s name=%q size=%d hasExpectedID=%t", m.Kind, m.Text, m.Size, m.MediaID == tc.media)
			}
			if m.CanDownload() != (tc.kind == "file" && tc.media != "") {
				t.Errorf("incorrect download availability for %s", tc.name)
			}
			if tc.kind == "file" && tc.media == "" {
				c := online(t)
				c.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
					t.Fatal("download without media authorization")
					return nil, nil
				})
				if err := c.Download(t.Context(), m, filepath.Join(t.TempDir(), "unused")); err == nil {
					t.Fatal("accepted unavailable file")
				}
			}
		})
	}
}

func TestLegacyFilenameUsedForRequestNotLocalPath(t *testing.T) {
	const name = "report: worksheet.pdf"
	var raw rawMessage
	data := `{"FromUserName":"filehelper","ToUserName":"@one","MsgType":49,"MsgId":"1","AppMsgType":6,"FileName":"report: worksheet.pdf","MediaId":"m","Content":""}`
	if err := json.Unmarshal([]byte(data), &raw); err != nil {
		t.Fatal(err)
	}
	m, ok := raw.message()
	if !ok || m.Text != "report_ worksheet.pdf" {
		t.Fatal("unsafe display name", m.Text)
	}
	c := online(t)
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Query().Get("filename") != name {
			t.Fatal("original wire name lost")
		}
		if strings.Contains(r.URL.RawQuery, ":") {
			t.Fatal("name not URL encoded")
		}
		return respond("sample"), nil
	})
	if err := c.Download(t.Context(), m, filepath.Join(t.TempDir(), m.Text)); err != nil {
		t.Fatal(err)
	}
}

func TestPhoneAndDesktopEchoesBeforeAndAfterSendReceipt(t *testing.T) {
	c := online(t)
	var local string
	acknowledged := false
	c.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case root + "webwxsendmsg":
			var body struct {
				Msg struct{ ClientMsgId, LocalID string }
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			local = body.Msg.ClientMsgId
			if local == "" || local != body.Msg.LocalID {
				t.Fatal("outbound message is missing its local identifier")
			}
			// The first sync completes while this request has no server receipt.
			messages, err := c.Sync(t.Context())
			if err != nil || len(messages) != 2 {
				t.Fatalf("early sync returned %d messages, err=%v", len(messages), err)
			}
			if !messages[0].Outgoing || messages[0].ClientID != local || messages[0].ID != "399" || messages[0].AlternateID != "402" {
				t.Error("early desktop echo was not correlated")
			}
			if messages[1].Outgoing || messages[1].ClientID != "" || messages[1].AlternateID != "" {
				t.Error("same text and sender on phone was misattributed")
			}
			acknowledged = true
			return respond(`{"BaseResponse":{"Ret":0},"MsgID":"402"}`), nil
		case root + "synccheck":
			return respond(`window.synccheck={retcode:"0",selector:"2"}`), nil
		case root + "webwxsync":
			clientFields := `"ClientMsgId":0,"LocalID":""`
			if !acknowledged {
				clientFields = fmt.Sprintf(`"ClientMsgId":%s`, local)
			}
			return respond(fmt.Sprintf(`{"BaseResponse":{"Ret":0},"AddMsgList":[{"MsgType":1,"MsgId":"399","NewMsgId":402,"Content":"same text","FromUserName":"@one","ToUserName":"filehelper",%s},{"MsgType":1,"MsgId":"400","NewMsgId":0,"Content":"same text","FromUserName":"@one","ToUserName":"filehelper","ClientMsgId":0,"LocalID":"0"}]}`, clientFields)), nil
		default:
			t.Fatalf("unexpected endpoint %s", r.URL.Path)
			return nil, nil
		}
	})
	receipt, err := c.SendText(t.Context(), "same text")
	if err != nil || !receipt.Outgoing || receipt.ID != "402" || receipt.ClientID != local {
		t.Fatal("send receipt missing identifiers", err)
	}
	messages, err := c.Sync(t.Context())
	if err != nil || len(messages) != 2 {
		t.Fatalf("later sync returned %d messages, err=%v", len(messages), err)
	}
	if !messages[0].Outgoing || messages[0].ClientID != local || messages[1].Outgoing {
		t.Error("server receipt did not distinguish local send from phone send")
	}
}

func TestFileDownloadNeedsMatchingSessionCookie(t *testing.T) {
	c := online(t)
	fileHost := serviceURL(regions[c.s.host].file, root, "webwxgetmedia")
	c.jar.SetCookies(fileHost, []*http.Cookie{{Name: "webwx_data_ticket", Domain: ".qq.com", Path: "/", MaxAge: -1}})
	// A cookie scoped to uploads cannot be used as authorization to download.
	c.jar.SetCookies(fileHost, []*http.Cookie{{Name: "webwx_data_ticket", Value: "upload-only", Path: root + "webwxuploadmedia", Secure: true}})
	c.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("download attempted without scoped session cookie")
		return nil, nil
	})
	m := Message{Kind: "file", Sender: "filehelper", MediaID: "authorized", Text: "notes.pptx"}
	if err := c.Download(t.Context(), m, filepath.Join(t.TempDir(), m.Text)); err == nil {
		t.Fatal("missing download authorization")
	}
	if ticket := c.dataTicket(c.s, "webwxuploadmedia"); ticket != "upload-only" {
		t.Fatal("endpoint-specific upload cookie was discarded")
	}
}
