// SPDX-License-Identifier: AGPL-3.0-only

package desktop

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

var ReleaseRepo string

type Update struct {
	Version, URL string
}

type release struct {
	Tag        string `json:"tag_name"`
	URL        string `json:"html_url"`
	Draft      bool   `json:"draft"`
	Prerelease bool   `json:"prerelease"`
	Assets     []struct {
		Name  string `json:"name"`
		State string `json:"state"`
	} `json:"assets"`
}

func repository() string {
	if ReleaseRepo != "" {
		return ReleaseRepo
	}
	if runtime.GOOS == "darwin" {
		return "Watertube-bilibili/wxfilehelper-macos"
	}
	return "Watertube-bilibili/wxfilehelper-desktop"
}

func (c *Controller) StartUpdateChecks() {
	c.mu.Lock()
	if c.closed || c.updateScheduler {
		c.mu.Unlock()
		return
	}
	c.updateScheduler = true
	c.mu.Unlock()
	go func() {
		if !pause(c.ctx, 3*time.Second) {
			return
		}
		for {
			c.CheckUpdate()
			if !pause(c.ctx, 6*time.Hour) {
				return
			}
		}
	}()
}

func (c *Controller) CheckUpdate() {
	c.mu.Lock()
	if c.closed || c.updateStatus == "checking" {
		c.mu.Unlock()
		return
	}
	c.updateStatus = "checking"
	c.revision++
	c.mu.Unlock()
	go func() {
		ctx, cancel := context.WithTimeout(c.ctx, 12*time.Second)
		defer cancel()
		update, err := checkRelease(ctx)
		c.mu.Lock()
		defer c.mu.Unlock()
		if c.closed {
			return
		}
		c.update = update
		switch {
		case err != nil:
			c.updateStatus = "failed"
		case update != nil:
			c.updateStatus = "available"
		default:
			c.updateStatus = "current"
		}
		c.revision++
	}()
}

func checkRelease(ctx context.Context) (*Update, error) {
	repo := repository()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://api.github.com/repos/"+repo+"/releases?per_page=30", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "WX-FileHelper/"+Version)
	client := &http.Client{
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GitHub responded with HTTP %d", resp.StatusCode)
	}
	var available []release
	if err := json.NewDecoder(io.LimitReader(resp.Body, 2<<20)).Decode(&available); err != nil {
		return nil, err
	}
	return newestRelease(available, repo), nil
}

var stableTag = regexp.MustCompile(`^v?([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})$`)

func versionRank(tag string) int64 {
	parts := stableTag.FindStringSubmatch(tag)
	if len(parts) == 0 {
		return -1
	}
	var rank int64
	for _, part := range parts[1:] {
		value, _ := strconv.Atoi(part)
		rank = rank*10000 + int64(value)
	}
	return rank
}

func newestRelease(available []release, repo string) *Update {
	best := versionRank(Version)
	var update *Update
	for _, r := range available {
		url := "https://github.com/" + repo + "/releases/tag/" + r.Tag
		rank := versionRank(r.Tag)
		if r.Draft || r.Prerelease || rank <= best || r.URL != url || !r.hasPackage() {
			continue
		}
		best, update = rank, &Update{Version: r.Tag, URL: url}
	}
	return update
}

func (r release) hasPackage() bool {
	base := "WXFileHelper-" + strings.TrimPrefix(r.Tag, "v")
	expected := []string{base + "-Windows-x64-Setup.exe", base + "-Windows-x64-Portable.exe"}
	if runtime.GOOS == "darwin" {
		arch := "x86_64"
		if runtime.GOARCH == "arm64" {
			arch = "arm64"
		}
		expected = []string{base + "-macOS-" + arch + ".dmg"}
	}
	for _, name := range expected {
		found := false
		for _, asset := range r.Assets {
			if asset.Name == name && asset.State == "uploaded" {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}
