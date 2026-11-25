// SPDX-License-Identifier: AGPL-3.0-only
//go:build darwin && cgo

package main

/*
#cgo CFLAGS: -fobjc-arc
#cgo LDFLAGS: -framework Cocoa
#include <stdlib.h>
int wxRunMac(int smoke);
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"sync"

	"github.com/Watertube-bilibili/wxfilehelper-desktop/native/internal/desktop"
)

var controller *desktop.Controller
var closeOnce sync.Once

func init() { runtime.LockOSThread() }

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--version" {
		fmt.Println(desktop.Version)
		return
	}
	smoke := C.int(0)
	if len(os.Args) == 2 && os.Args[1] == "--smoke-test" {
		smoke = 1
	}
	controller = desktop.New()
	if smoke == 0 {
		controller.StartUpdateChecks()
	}
	code := int(C.wxRunMac(smoke))
	wxShutdown()
	os.Exit(code)
}

//export wxShutdown
func wxShutdown() { closeOnce.Do(controller.Close) }

//export wxSnapshot
func wxSnapshot(seen C.ulonglong, force C.int) *C.char {
	s := controller.Snapshot()
	if force == 0 && s.Revision == uint64(seen) {
		return nil
	}
	data, err := json.Marshal(s)
	if err != nil {
		return nil
	}
	return C.CString(string(data))
}

//export wxAction
func wxAction(action *C.char, account C.ulonglong, argument *C.char, extra *C.char, index C.longlong) *C.char {
	id := uint64(account)
	value := C.GoString(argument)
	var err error
	switch C.GoString(action) {
	case "add":
		var newID uint64
		newID, err = controller.AddAccount()
		if err == nil {
			err = controller.SetActive(newID)
		}
	case "select":
		err = controller.SetActive(id)
	case "close":
		err = controller.RemoveAccount(id)
	case "login":
		err = controller.Start(id)
	case "signout":
		err = controller.SignOut(id)
	case "queue":
		var paths []string
		if err = json.Unmarshal([]byte(value), &paths); err == nil {
			err = controller.Queue(id, paths)
		}
	case "remove":
		err = controller.RemoveFile(id, int(index))
	case "clear":
		err = controller.ClearFiles(id)
	case "send":
		err = controller.Send(id, value)
	case "stop":
		err = controller.StopSending(id)
	case "download":
		err = controller.Download(id, value, C.GoString(extra))
	case "update":
		controller.CheckUpdate()
	default:
		err = fmt.Errorf("未知操作 / Unknown action")
	}
	if err != nil {
		return C.CString(err.Error())
	}
	return nil
}
