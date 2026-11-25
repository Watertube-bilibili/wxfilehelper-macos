// SPDX-License-Identifier: AGPL-3.0-only
#import <Cocoa/Cocoa.h>
#import "_cgo_export.h"

static NSString *WXStr(id value) { return [value isKindOfClass:NSString.class] ? value : @""; }
static NSArray *WXList(id value) { return [value isKindOfClass:NSArray.class] ? value : @[]; }
static NSString *WXAction(const char *op, NSNumber *account, NSString *value, NSString *extra, NSInteger index) {
    char *error = wxAction((char *)op, account.unsignedLongLongValue, (char *)(value ?: @"").UTF8String,
                           (char *)(extra ?: @"").UTF8String, index);
    if (!error) return nil;
    NSString *message = [NSString stringWithUTF8String:error]; free(error);
    return message ?: @"操作失败 / Operation failed";
}
static NSString *WXSize(id size) { return [NSByteCountFormatter stringFromByteCount:[size longLongValue] countStyle:NSByteCountFormatterCountStyleFile]; }
static BOOL WXIsFile(NSDictionary *message) {
    NSString *kind = WXStr(message[@"Kind"]);
    return ([kind isEqual:@"file"] || [kind isEqual:@"image"] || [kind isEqual:@"video"]) && WXStr(message[@"ID"]).length;
}
static NSTextField *WXLabel(NSString *text, CGFloat size, NSColor *color) {
    NSTextField *label = [NSTextField labelWithString:text]; label.font = [NSFont systemFontOfSize:size];
    label.textColor = color; label.lineBreakMode = NSLineBreakByTruncatingTail; return label;
}
static NSButton *WXButton(NSString *title, id target, SEL action) { return [NSButton buttonWithTitle:title target:target action:action]; }
static NSRect WXRect(CGFloat x, CGFloat y, CGFloat w, CGFloat h) { return NSMakeRect(round(x),round(y),MAX(0,round(w)),MAX(0,round(h))); }

@class WXMac;
@interface WXSurface : NSView
@property(weak) WXMac *owner;
@end
@interface WXMac : NSObject <NSApplicationDelegate, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate, NSTextViewDelegate>
@property(strong) NSWindow *window;
@property(strong) WXSurface *root;
@property(strong) NSVisualEffectView *rail;
@property(strong) NSTextField *railTitle, *status, *hint, *progressLabel, *queueLabel;
@property(strong) NSButton *chats, *files, *updates, *releaseButton, *plus, *refreshQR, *attach, *send, *save, *remove, *stop;
@property(strong) NSSegmentedControl *tabs, *filter;
@property(strong) NSPopUpButton *accountMenu;
@property(strong) NSImageView *qr;
@property(strong) NSProgressIndicator *progress;
@property(strong) NSScrollView *historyPane, *draftPane, *queuePane;
@property(strong) NSTableView *history, *queue;
@property(strong) NSTextView *draft;
@property(strong) NSTimer *poll;
@property(strong) NSDictionary *state, *account;
@property(strong) NSArray *rows, *staged;
@property(strong) NSMutableDictionary<NSNumber *,NSString *> *drafts;
@property(strong) NSMutableDictionary<NSNumber *,NSDictionary *> *pending;
@property(strong) NSMutableDictionary<NSNumber *,NSNumber *> *authState;
@property(strong) NSNumber *active;
@property(strong) NSString *qrSource;
@property(strong) NSDateFormatter *timeFormat;
@property BOOL fileOnly, smoke;
@property unsigned long long revision;
- (void)layout;
- (void)render:(BOOL)force;
- (BOOL)acceptPaths:(NSArray *)paths account:(NSNumber *)key;
@end

@implementation WXSurface
- (BOOL)isFlipped { return YES; }
- (NSDragOperation)draggingEntered:(id<NSDraggingInfo>)sender {
    return [self.owner.account[@"SignedIn"] boolValue] && ![self.owner.account[@"Busy"] boolValue] &&
        [sender.draggingPasteboard canReadObjectForClasses:@[NSURL.class] options:@{NSPasteboardURLReadingFileURLsOnlyKey:@YES}]
        ? NSDragOperationCopy : NSDragOperationNone;
}
- (BOOL)performDragOperation:(id<NSDraggingInfo>)sender {
    NSArray *urls = [sender.draggingPasteboard readObjectsForClasses:@[NSURL.class] options:@{NSPasteboardURLReadingFileURLsOnlyKey:@YES}];
    NSMutableArray *paths = [NSMutableArray array];
    for (NSURL *u in urls) if (u.isFileURL) [paths addObject:u.path];
    return [self.owner acceptPaths:paths account:self.owner.active];
}
@end

@implementation WXMac
- (NSScrollView *)tablePane:(NSTableView *)table {
    NSScrollView *pane = [NSScrollView new];
    pane.hasVerticalScroller = YES; pane.autohidesScrollers = YES; pane.borderType = NSNoBorder;
    table.delegate = self; table.dataSource = self; table.headerView = nil;
    table.allowsMultipleSelection = NO; table.intercellSpacing = NSMakeSize(0,2);
    table.columnAutoresizingStyle = NSTableViewLastColumnOnlyAutoresizingStyle;
    NSTableColumn *column = [[NSTableColumn alloc] initWithIdentifier:@"item"];
    column.resizingMask = NSTableColumnAutoresizingMask; [table addTableColumn:column];
    pane.documentView = table; return pane;
}
- (void)installMenus {
    NSMenu *bar = [NSMenu new], *app = [NSMenu new], *file = [NSMenu new], *edit = [NSMenu new];
    [bar addItemWithTitle:@"" action:nil keyEquivalent:@""].submenu = app;
    [app addItemWithTitle:@"关于文件传输助手 / About" action:@selector(about:) keyEquivalent:@""].target = self;
    [app addItemWithTitle:@"检查更新 / Check for Updates" action:@selector(checkUpdate:) keyEquivalent:@""].target = self;
    [app addItem:NSMenuItem.separatorItem];
    [app addItemWithTitle:@"退出 / Quit" action:@selector(terminate:) keyEquivalent:@"q"];
    [bar addItemWithTitle:@"传输 / Transfer" action:nil keyEquivalent:@""].submenu = file;
    [file addItemWithTitle:@"添加文件 / Add Files…" action:@selector(pick:) keyEquivalent:@"o"].target = self;
    [file addItemWithTitle:@"发送 / Send" action:@selector(sendNow:) keyEquivalent:@"\r"].target = self;
    [file addItemWithTitle:@"另存为 / Save As…" action:@selector(saveSelected:) keyEquivalent:@"s"].target = self;
    [file addItem:NSMenuItem.separatorItem];
    [file addItemWithTitle:@"添加账号 / Add Account" action:@selector(addTab:) keyEquivalent:@"t"].target = self;
    NSMenuItem *switchAccount = [file addItemWithTitle:@"切换账号 / Switch Account" action:@selector(nextTab:) keyEquivalent:@"\t"];
    switchAccount.target = self;
    switchAccount.keyEquivalentModifierMask = NSEventModifierFlagControl;
    [bar addItemWithTitle:@"编辑 / Edit" action:nil keyEquivalent:@""].submenu = edit;
    [edit addItemWithTitle:@"撤销 / Undo" action:@selector(undo:) keyEquivalent:@"z"];
    [edit addItemWithTitle:@"剪切 / Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [edit addItemWithTitle:@"复制 / Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [edit addItemWithTitle:@"粘贴 / Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [edit addItemWithTitle:@"全选 / Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    NSApp.mainMenu = bar;
}
- (void)buildWindow {
    self.state = @{}; self.account = @{}; self.rows = @[]; self.staged = @[];
    self.drafts = [NSMutableDictionary dictionary]; self.pending = [NSMutableDictionary dictionary]; self.authState = [NSMutableDictionary dictionary];
    self.timeFormat = [NSDateFormatter new]; self.timeFormat.timeStyle = NSDateFormatterShortStyle;
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,960,660)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskResizable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskClosable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"文件传输助手 · WX FileHelper"; self.window.contentMinSize = NSMakeSize(560,400);
    self.window.collectionBehavior = NSWindowCollectionBehaviorFullScreenPrimary;
    self.window.delegate = self; self.window.releasedWhenClosed = NO;
    self.root = [WXSurface new]; self.root.owner = self; self.window.contentView = self.root;
    [self.root registerForDraggedTypes:@[NSPasteboardTypeFileURL]];
    self.rail = [NSVisualEffectView new]; self.rail.material = NSVisualEffectMaterialSidebar; self.rail.blendingMode = NSVisualEffectBlendingModeBehindWindow;
    self.railTitle = WXLabel(@"文件传输助手",17,NSColor.labelColor); self.railTitle.font = [NSFont boldSystemFontOfSize:17];
    self.chats = WXButton(@"文件传输",self,@selector(showChats:)); self.files = WXButton(@"本次文件",self,@selector(showFiles:));
    self.updates = WXButton(@"检查更新",self,@selector(checkUpdate:)); self.releaseButton = WXButton(@"查看新版本",self,@selector(openRelease:));
    self.tabs = [[NSSegmentedControl alloc] initWithFrame:NSZeroRect]; self.tabs.segmentStyle = NSSegmentStyleRounded;
    self.tabs.target = self; self.tabs.action = @selector(selectTab:); self.tabs.trackingMode = NSSegmentSwitchTrackingSelectOne;
    self.plus = WXButton(@"+",self,@selector(addTab:)); self.plus.toolTip = @"添加第二个账号 / Add another account";
    self.accountMenu = [[NSPopUpButton alloc] initWithFrame:NSZeroRect pullsDown:YES]; [self.accountMenu addItemWithTitle:@"更多"];
    for (NSArray *p in @[@[@"检查更新 / Check Updates",@"checkUpdate:"],@[@"查看新版本 / Open Release",@"openRelease:"],@[@"退出账号 / Sign Out",@"signOut:"],@[@"关闭标签 / Close Account",@"closeTab:"],@[@"关于 / About",@"about:"]]) {
        [self.accountMenu addItemWithTitle:p[0]]; self.accountMenu.lastItem.target = self; self.accountMenu.lastItem.action = NSSelectorFromString(p[1]);
    }
    self.status = WXLabel(@"",13,NSColor.secondaryLabelColor);
    self.filter = [NSSegmentedControl segmentedControlWithLabels:@[@"全部",@"文件"] trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changeFilter:)];
    self.qr = [NSImageView new]; self.qr.imageScaling = NSImageScaleProportionallyUpOrDown;
    [self.qr setAccessibilityLabel:@"微信登录二维码 / WeChat sign-in QR code"];
    self.hint = WXLabel(@"",15,NSColor.labelColor); self.hint.alignment = NSTextAlignmentCenter; self.hint.usesSingleLineMode = NO;
    self.hint.maximumNumberOfLines = 3; self.hint.lineBreakMode = NSLineBreakByWordWrapping;
    self.refreshQR = WXButton(@"刷新二维码",self,@selector(refresh:));
    self.history = [NSTableView new]; self.historyPane = [self tablePane:self.history];
    self.history.target = self; self.history.doubleAction = @selector(openSelection:);
    self.queue = [NSTableView new]; self.queuePane = [self tablePane:self.queue]; self.queue.rowHeight = 24;
    self.queueLabel = WXLabel(@"待发送文件",12,NSColor.secondaryLabelColor); self.remove = WXButton(@"移除所选",self,@selector(removeFile:));
    self.draftPane = [NSScrollView new]; self.draftPane.borderType = NSBezelBorder; self.draftPane.hasVerticalScroller = YES; self.draftPane.autohidesScrollers = YES;
    self.draft = [[NSTextView alloc] initWithFrame:NSMakeRect(0,0,300,45)]; self.draft.richText = NO;
    self.draft.allowsUndo = YES; self.draft.delegate = self; self.draft.verticallyResizable = YES; self.draft.horizontallyResizable = NO;
    self.draft.autoresizingMask = NSViewWidthSizable; self.draft.textContainer.widthTracksTextView = YES; self.draft.textContainerInset = NSMakeSize(6,5);
    self.draftPane.documentView = self.draft; [self.draft setAccessibilityLabel:@"消息草稿 / Message draft"];
    self.attach = WXButton(@"添加文件…",self,@selector(pick:)); self.save = WXButton(@"另存为…",self,@selector(saveSelected:));
    self.send = WXButton(@"发送",self,@selector(sendNow:)); self.send.bezelColor = NSColor.controlAccentColor; self.send.toolTip = @"发送文字及待发送文件 / Send (⌘↩)";
    self.stop = WXButton(@"当前文件后停止",self,@selector(stopSending:));
    self.progress = [NSProgressIndicator new]; self.progress.indeterminate = YES; self.progress.style = NSProgressIndicatorStyleBar;
    self.progressLabel = WXLabel(@"",11,NSColor.secondaryLabelColor);
    for (NSView *v in @[self.rail,self.railTitle,self.chats,self.files,self.updates,self.releaseButton,self.tabs,self.plus,self.accountMenu,self.status,self.filter,self.qr,self.hint,self.refreshQR,self.historyPane,self.queueLabel,self.remove,self.queuePane,self.draftPane,self.attach,self.save,self.send,self.stop,self.progress,self.progressLabel]) [self.root addSubview:v];
    [self installMenus]; [self.window center]; [self render:YES];
}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    [self buildWindow]; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
    [self command:"login" for:self.active value:nil extra:nil index:0];
    self.poll = [NSTimer scheduledTimerWithTimeInterval:0.25 target:self selector:@selector(tick:) userInfo:nil repeats:YES];
    [[NSRunLoop mainRunLoop] addTimer:self.poll forMode:NSRunLoopCommonModes];
}
- (void)tick:(NSTimer *)timer { [self render:NO]; }
- (void)windowDidResize:(NSNotification *)note { [self layout]; }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app { return YES; }
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    for (NSDictionary *a in WXList(self.state[@"Accounts"])) {
        if ([a[@"Busy"] boolValue] || [a[@"Downloading"] boolValue] || WXList(a[@"Files"]).count || self.drafts[a[@"ID"]].length) {
            if (![self confirm:@"退出并丢弃未完成的传输？" detail:@"队列和未发送的文字仅保留在本次会话。"]) return NSTerminateCancel;
            break;
        }
    }
    [self.poll invalidate]; wxShutdown(); return NSTerminateNow;
}
- (BOOL)windowShouldClose:(NSWindow *)sender { [NSApp terminate:self]; return NO; }
- (BOOL)command:(const char *)op for:(NSNumber *)account value:(NSString *)value extra:(NSString *)extra index:(NSInteger)index {
    NSString *error = WXAction(op,account,value,extra,index);
    if (error) {
        NSAlert *a = [NSAlert new]; a.messageText = @"操作未完成 / Operation failed"; a.informativeText = error;
        [a beginSheetModalForWindow:self.window completionHandler:nil]; return NO;
    }
    [self render:YES]; return YES;
}
- (BOOL)confirm:(NSString *)title detail:(NSString *)detail {
    NSAlert *a = [NSAlert new]; a.messageText = title; a.informativeText = detail; [a addButtonWithTitle:@"取消"]; [a addButtonWithTitle:@"继续"];
    return [a runModal] == NSAlertSecondButtonReturn;
}
- (void)render:(BOOL)force {
    char *json = wxSnapshot(self.revision, force);
    if (!json) return;
    NSData *data = [NSData dataWithBytesNoCopy:json length:strlen(json) freeWhenDone:YES];
    NSDictionary *state = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    if (![state isKindOfClass:NSDictionary.class]) return;
    [self applySnapshot:state];
}
- (void)applySnapshot:(NSDictionary *)state {
    BOOL wasSaving = [self.account[@"Downloading"] boolValue];
    self.state = state; self.revision = [state[@"Revision"] unsignedLongLongValue];
    NSArray *accounts = WXList(state[@"Accounts"]); NSNumber *selected = state[@"Active"];
    BOOL changed = ![self.active isEqual:selected]; self.active = selected;
    self.tabs.segmentCount = accounts.count;
    [accounts enumerateObjectsUsingBlock:^(NSDictionary *a, NSUInteger i, BOOL *stop) {
        NSNumber *key = a[@"ID"]; BOOL online = [a[@"SignedIn"] boolValue];
        NSNumber *epoch = a[@"DraftEpoch"];
        if (self.authState[key] && ![self.authState[key] isEqual:epoch]) {
            [self.drafts removeObjectForKey:key]; [self.pending removeObjectForKey:key];
            if ([key isEqual:selected]) { self.draft.string = @""; [self.draft.undoManager removeAllActions]; }
        }
        self.authState[key] = epoch;
        NSDictionary *pending = self.pending[key];
        if (pending && ![a[@"Busy"] boolValue]) {
            BOOL delivered = NO;
            for (NSDictionary *m in [WXList(a[@"Messages"]) reverseObjectEnumerator]) {
                if ([WXStr(m[@"ID"]) isEqual:pending[@"last"]]) break;
                if ([m[@"Outgoing"] boolValue] && [WXStr(m[@"Text"]) isEqual:pending[@"text"]]) { delivered = YES; break; }
            }
            if (delivered && [self.drafts[key] isEqual:pending[@"text"]]) {
                [self.drafts removeObjectForKey:key]; if ([key isEqual:selected]) self.draft.string = @"";
            }
            [self.pending removeObjectForKey:key];
        }
        NSString *name = !online ? @"" : WXStr(a[@"Name"]);
        if (name.length > 12) name = [[name substringToIndex:NSMaxRange([name rangeOfComposedCharacterSequenceAtIndex:11])] stringByAppendingString:@"…"];
        [self.tabs setLabel:name.length ? name : [NSString stringWithFormat:@"账号 %lu",(unsigned long)i+1] forSegment:i];
        if ([key isEqual:selected]) { self.account = a; self.tabs.selectedSegment = i; }
    }];
    if (changed) {
        self.draft.string = self.drafts[selected] ?: @""; [self.draft.undoManager removeAllActions];
        [self.history deselectAll:nil]; [self.queue deselectAll:nil];
    }
    NSString *st = WXStr(self.account[@"Status"]), *error = WXStr(self.account[@"Error"]);
    NSDictionary *labels = @{@"idle":@"等待登录",@"connecting":@"正在连接…",@"scan":@"等待扫码",@"scanned":@"请在手机上确认",@"online":@"已连接",@"reconnecting":@"正在重新连接…",@"expired":@"登录已过期"};
    NSString *updateInfo = [@{@"checking":@"正在检查更新…",@"available":@"有新版本可用",@"failed":@"更新检查失败",@"current":@"当前已是最新版"} objectForKey:WXStr(state[@"UpdateStatus"])];
    NSString *status = labels[st] ?: st;
    if ([self.account[@"Downloading"] boolValue]) status = @"正在保存文件…";
    else if (wasSaving && !changed && [self.account[@"SignedIn"] boolValue] && !error.length) status = @"文件已保存";
    self.status.stringValue = error.length ? error : updateInfo.length ? [NSString stringWithFormat:@"%@   ·   %@",status,updateInfo] : status;
    self.status.toolTip = self.status.stringValue; self.status.textColor = error.length ? NSColor.systemRedColor : NSColor.secondaryLabelColor;
    NSString *qr = WXStr(self.account[@"QR"]);
    if (![self.qrSource isEqual:qr]) {
        self.qrSource = qr; NSData *bytes = [[NSData alloc] initWithBase64EncodedString:qr options:0];
        self.qr.image = bytes.length ? [[NSImage alloc] initWithData:bytes] : nil;
    }
    self.hint.stringValue = [st isEqual:@"scan"] ? @"用手机微信扫一扫\nScan with WeChat on your phone" : [st isEqual:@"scanned"] ? @"请在手机微信上确认登录\nConfirm sign-in on your phone" : (error.length ? error : status);
    self.refreshQR.title = ([st isEqual:@"idle"] || [st isEqual:@"expired"]) ? @"扫码登录" : @"刷新二维码";
    NSMutableArray *rows = [NSMutableArray array];
    for (NSDictionary *m in WXList(self.account[@"Messages"])) if (!self.fileOnly || WXIsFile(m)) [rows addObject:m];
    if (changed || ![self.rows isEqual:rows]) {
        NSString *keep = !changed ? WXStr([self selectedMessage][@"ID"]) : @"";
        BOOL follow = changed || !self.rows.count || NSMaxY(self.history.visibleRect) >= NSHeight(self.history.bounds)-8;
        self.rows = rows; [self.history reloadData];
        if (keep.length) {
            NSUInteger idx = [rows indexOfObjectPassingTest:^BOOL(NSDictionary *m, NSUInteger i, BOOL *stop){ return [WXStr(m[@"ID"]) isEqual:keep]; }];
            if (idx != NSNotFound) [self.history selectRowIndexes:[NSIndexSet indexSetWithIndex:idx] byExtendingSelection:NO];
        }
        if (follow && rows.count) [self.history scrollRowToVisible:rows.count-1];
    }
    NSArray *staged = WXList(self.account[@"Files"]);
    if (changed || ![staged isEqual:self.staged]) { self.staged = staged; [self.queue reloadData]; }
    self.queueLabel.stringValue = [NSString stringWithFormat:@"待发送文件  %lu",(unsigned long)staged.count];
    int64_t sent = [self.account[@"Sent"] longLongValue], total = [self.account[@"Total"] longLongValue];
    self.progress.indeterminate = total <= 0;
    if (total > 0) { self.progress.maxValue = (double)total; self.progress.doubleValue = (double)sent; }
    self.progressLabel.stringValue = total ? [NSString stringWithFormat:@"%@ / %@",WXSize(@(sent)),WXSize(@(total))] : @"正在传输…";
    self.filter.selectedSegment = self.fileOnly ? 1 : 0;
    self.chats.state = self.fileOnly ? NSControlStateValueOff : NSControlStateValueOn;
    self.files.state = self.fileOnly ? NSControlStateValueOn : NSControlStateValueOff;
    [self layout];
}
- (void)updateButtons {
    BOOL online = [self.account[@"SignedIn"] boolValue], busy = [self.account[@"Busy"] boolValue];
    self.send.enabled = online && !busy && (self.draft.string.length || self.staged.count);
    self.attach.enabled = online && !busy; self.draft.editable = online && !busy;
    self.remove.enabled = online && !busy && self.queue.selectedRow >= 0;
    self.save.enabled = online && ![self.account[@"Downloading"] boolValue] && [[[self selectedMessage] objectForKey:@"CanSave"] boolValue];
}
- (void)layout {
    if (!self.send) return;
    CGFloat width = NSWidth(self.root.bounds), height = NSHeight(self.root.bounds);
    BOOL sidebar = width >= 840 && height >= 500;
    CGFloat rail = sidebar ? 168 : 0, pad = 14, left = rail + pad;
    CGFloat usable = width-left-pad, ctl = 30;
    BOOL online = [self.account[@"SignedIn"] boolValue], busy = [self.account[@"Busy"] boolValue];
    for (NSView *v in @[self.rail,self.railTitle,self.chats,self.files,self.updates]) v.hidden = !sidebar;
    self.rail.frame = WXRect(0,0,rail,height); self.railTitle.frame = WXRect(18,23,136,24);
    self.chats.frame = WXRect(10,69,148,32); self.files.frame = WXRect(10,108,148,32);
    self.updates.frame = WXRect(10,height-43,148,30);
    self.releaseButton.hidden = !sidebar || ![self.state[@"Update"] isKindOfClass:NSDictionary.class];
    self.releaseButton.frame = WXRect(10,height-78,148,30);
    self.accountMenu.frame = WXRect(width-pad-67,10,67,ctl);
    NSUInteger count = WXList(self.state[@"Accounts"]).count;
    CGFloat tabWidth = MIN(count == 2 ? 260 : 130,usable-116);
    self.tabs.frame = WXRect(left,10,tabWidth,ctl); self.plus.frame = WXRect(left+tabWidth+4,10,34,ctl);
    self.plus.hidden = count >= 2;
    CGFloat statusY = 16+ctl;
    self.filter.hidden = sidebar || !online; self.filter.frame = WXRect(width-pad-106,statusY,106,26);
    self.status.font = [NSFont systemFontOfSize:13];
    self.status.frame = WXRect(left,statusY+3,usable-(self.filter.hidden ? 0 : 112),22);
    CGFloat top = statusY + 32;
    self.qr.hidden = self.hint.hidden = self.refreshQR.hidden = online;
    self.historyPane.hidden = self.draftPane.hidden = self.attach.hidden = self.send.hidden = self.save.hidden = !online;
    self.queuePane.hidden = self.queueLabel.hidden = self.remove.hidden = !online || !self.staged.count;
    self.stop.hidden = self.progress.hidden = self.progressLabel.hidden = !online || !busy;
    if (!online) {
        CGFloat lower = height-top-12;
        CGFloat qr = MIN(260,MAX(88,MIN(usable-20,lower-112)));
        CGFloat qy = top+MAX(0,(lower-qr-99)/2);
        self.qr.frame = WXRect(left+(usable-qr)/2,qy,qr,qr); self.hint.font = [NSFont systemFontOfSize:15];
        self.hint.frame = WXRect(left,qy+qr+6,usable,45);
        self.refreshQR.frame = WXRect(left+(usable-145)/2,qy+qr+54,145,ctl);
    } else {
        CGFloat bottom = height-pad-ctl, sendWidth = 85;
        self.attach.frame = WXRect(left,bottom,105,ctl); self.save.frame = WXRect(left+110,bottom,88,ctl);
        self.send.frame = WXRect(width-pad-sendWidth,bottom,sendWidth,ctl);
        self.stop.frame = WXRect(width-pad-sendWidth-133,bottom,128,ctl);
        CGFloat composerHeight = height >= 540 ? 65 : 46, composerY = bottom-composerHeight-6;
        self.draftPane.frame = WXRect(left,composerY,usable,composerHeight);
        self.draft.font = [NSFont systemFontOfSize:14];
        CGFloat historyEnd = composerY-8;
        if (busy) {
            self.progress.frame = WXRect(left,historyEnd-14,MAX(100,usable-170),12);
            self.progressLabel.frame = WXRect(width-pad-157,historyEnd-17,157,17); historyEnd -= 21;
        }
        if (self.staged.count) {
            CGFloat qh = MIN((CGFloat)self.staged.count*26,MAX(28,MIN(110,(height-top)*0.18)));
            self.queuePane.frame = WXRect(left,historyEnd-qh,usable,qh); self.queue.rowHeight = 24;
            self.queueLabel.frame = WXRect(left,historyEnd-qh-24,usable-110,23);
            self.remove.frame = WXRect(width-pad-92,historyEnd-qh-26,92,26);
            historyEnd -= qh+30;
        }
        self.historyPane.frame = WXRect(left,top,usable,MAX(40,historyEnd-top));
        self.history.rowHeight = 46;
    }
    [self updateButtons];
}
- (NSDictionary *)selectedMessage {
    NSInteger row = self.history.selectedRow;
    return row >= 0 && row < (NSInteger)self.rows.count ? self.rows[row] : nil;
}
- (NSInteger)numberOfRowsInTableView:(NSTableView *)table { return (table == self.queue ? self.staged : self.rows).count; }
- (NSView *)tableView:(NSTableView *)table viewForTableColumn:(NSTableColumn *)column row:(NSInteger)row {
    BOOL queued = table == self.queue;
    NSArray *source = queued ? self.staged : self.rows;
    if (row < 0 || row >= (NSInteger)source.count) return nil;
    NSDictionary *item = source[row];
    NSTableCellView *cell = [table makeViewWithIdentifier:@"row" owner:self];
    if (!cell) {
        cell = [[NSTableCellView alloc] initWithFrame:NSMakeRect(0,0,MAX(100,column.width),table.rowHeight)];
        cell.identifier = @"row";
        NSTextField *text = WXLabel(@"",14,NSColor.labelColor); text.frame = NSInsetRect(cell.bounds,8,1);
        text.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable; text.usesSingleLineMode = NO;
        text.maximumNumberOfLines = queued ? 1 : 2; [cell addSubview:text]; cell.textField = text;
    }
    NSString *body = WXStr(item[queued ? @"Name" : @"Text"]);
    if (queued) {
        cell.textField.stringValue = [NSString stringWithFormat:@"%@    %@",body,WXSize(item[@"Size"])];
        cell.textField.font = [NSFont systemFontOfSize:13]; cell.toolTip = WXStr(item[@"Path"]);
    } else {
        NSString *when = [self.timeFormat stringFromDate:[NSDate dateWithTimeIntervalSince1970:[item[@"Timestamp"] doubleValue]]];
        NSString *kind = WXIsFile(item) ? [NSString stringWithFormat:@" · 文件 %@",WXSize(item[@"Size"])] : @"";
        NSString *meta = [NSString stringWithFormat:@"%@   %@%@\n",[item[@"Outgoing"] boolValue] ? @"已发送" : @"收到",when,kind];
        NSMutableAttributedString *a = [[NSMutableAttributedString alloc] initWithString:meta attributes:@{NSFontAttributeName:[NSFont systemFontOfSize:11],NSForegroundColorAttributeName:NSColor.secondaryLabelColor}];
        NSString *line = [[body componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet] componentsJoinedByString:@" "];
        [a appendAttributedString:[[NSAttributedString alloc] initWithString:line attributes:@{NSFontAttributeName:[NSFont systemFontOfSize:15],NSForegroundColorAttributeName:NSColor.labelColor}]];
        cell.textField.attributedStringValue = a; cell.toolTip = body;
    }
    return cell;
}
- (void)tableViewSelectionDidChange:(NSNotification *)note { [self updateButtons]; }
- (void)textDidChange:(NSNotification *)note {
    if (self.active && note.object == self.draft) self.drafts[self.active] = self.draft.string;
    [self updateButtons];
}
- (void)showChats:(id)sender { self.fileOnly = NO; [self render:YES]; }
- (void)showFiles:(id)sender { self.fileOnly = YES; [self render:YES]; }
- (void)changeFilter:(id)sender { self.fileOnly = self.filter.selectedSegment == 1; [self render:YES]; }
- (void)selectTab:(id)sender {
    NSInteger i = self.tabs.selectedSegment; NSArray *accounts = WXList(self.state[@"Accounts"]);
    if (i >= 0 && i < (NSInteger)accounts.count) [self command:"select" for:accounts[i][@"ID"] value:nil extra:nil index:0];
}
- (void)nextTab:(id)sender {
    if (self.tabs.segmentCount == 2) { self.tabs.selectedSegment = 1-self.tabs.selectedSegment; [self selectTab:sender]; }
}
- (void)addTab:(id)sender {
    if (WXList(self.state[@"Accounts"]).count < 2 && [self command:"add" for:self.active value:nil extra:nil index:0] && !self.smoke)
        [self command:"login" for:self.active value:nil extra:nil index:0];
}
- (void)refresh:(id)sender { if (![self.account[@"SignedIn"] boolValue]) [self command:"login" for:self.active value:nil extra:nil index:0]; }
- (void)signOut:(id)sender {
    if (![self.account[@"SignedIn"] boolValue] || ![self confirm:@"退出当前账号？" detail:@"本标签的会话、队列和草稿将清空。"]) return;
    [self command:"signout" for:self.active value:nil extra:nil index:0];
}
- (void)closeTab:(id)sender {
    if (WXList(self.state[@"Accounts"]).count < 2 || ![self confirm:@"关闭此账号标签？" detail:@"本标签将退出登录并清空本次会话。"]) return;
    NSNumber *key = self.active;
    if ([self command:"close" for:key value:nil extra:nil index:0]) {
        [self.drafts removeObjectForKey:key]; [self.pending removeObjectForKey:key]; [self.authState removeObjectForKey:key];
    }
}
- (BOOL)acceptPaths:(NSArray *)paths account:(NSNumber *)key {
    if (!paths.count || !key) return NO;
    NSData *json = [NSJSONSerialization dataWithJSONObject:paths options:0 error:NULL];
    if (!json) return NO;
    return [self command:"queue" for:key value:[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding] extra:nil index:0];
}
- (void)pick:(id)sender {
    if (!self.attach.enabled) return;
    NSNumber *target = self.active;
    NSOpenPanel *p = [NSOpenPanel openPanel]; p.canChooseFiles = YES; p.canChooseDirectories = NO; p.allowsMultipleSelection = YES;
    [p beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse answer) {
        if (answer != NSModalResponseOK) return;
        NSMutableArray *paths = [NSMutableArray array]; for (NSURL *url in p.URLs) if (url.isFileURL) [paths addObject:url.path];
        [self acceptPaths:paths account:target];
    }];
}
- (void)sendNow:(id)sender {
    if (!self.send.enabled) return;
    NSString *text = self.draft.string; NSNumber *key = self.active;
    if (text.length) self.pending[key] = @{@"text":text,@"last":WXStr([WXList(self.account[@"Messages"]) lastObject][@"ID"])};
    if (![self command:"send" for:key value:text extra:nil index:0]) [self.pending removeObjectForKey:key];
}
- (void)removeFile:(id)sender {
    NSInteger index = self.queue.selectedRow;
    if (self.remove.enabled) [self command:"remove" for:self.active value:nil extra:nil index:index];
}
- (void)stopSending:(id)sender { if ([self.account[@"Busy"] boolValue]) [self command:"stop" for:self.active value:nil extra:nil index:0]; }
- (void)saveSelected:(id)sender {
    NSDictionary *msg = [self selectedMessage]; if (!self.save.enabled || !msg) return;
    NSNumber *key = self.active; NSString *messageID = WXStr(msg[@"ID"]);
    NSSavePanel *p = [NSSavePanel savePanel]; p.canCreateDirectories = YES;
    NSString *name = WXStr(msg[@"Text"]).lastPathComponent;
    p.nameFieldStringValue = name.length ? name : @"download";
    [p beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse answer) {
        if (answer == NSModalResponseOK && p.URL.isFileURL) [self command:"download" for:key value:messageID extra:p.URL.path index:0];
    }];
}
- (void)openSelection:(id)sender {
    NSDictionary *msg = [self selectedMessage]; if (!msg) return;
    if ([msg[@"CanSave"] boolValue]) { [self saveSelected:sender]; return; }
    if (WXIsFile(msg)) {
        NSAlert *alert = [NSAlert new];
        alert.messageText = WXStr(msg[@"Text"]);
        alert.informativeText = @"微信没有提供此文件的下载信息 / WeChat did not supply download details for this file.";
        [alert beginSheetModalForWindow:self.window completionHandler:nil];
        return;
    }
    NSAlert *detail = [NSAlert new]; detail.messageText = [msg[@"Outgoing"] boolValue] ? @"已发送的文字" : @"收到的文字";
    NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSMakeRect(0,0,400,170)];
    scroll.hasVerticalScroller = YES; scroll.borderType = NSBezelBorder;
    NSTextView *text = [[NSTextView alloc] initWithFrame:scroll.contentView.bounds]; text.editable = NO;
    text.verticallyResizable = YES; text.textContainer.widthTracksTextView = YES; text.autoresizingMask = NSViewWidthSizable;
    text.font = [NSFont systemFontOfSize:15]; text.string = WXStr(msg[@"Text"]); scroll.documentView = text; detail.accessoryView = scroll;
    [detail beginSheetModalForWindow:self.window completionHandler:nil];
}
- (void)checkUpdate:(id)sender { [self command:"update" for:self.active value:nil extra:nil index:0]; }
- (void)openRelease:(id)sender {
    NSDictionary *update = self.state[@"Update"]; if (![update isKindOfClass:NSDictionary.class]) return;
    NSURL *url = [NSURL URLWithString:WXStr(update[@"URL"])];
    if ([url.scheme isEqual:@"https"] && [url.host.lowercaseString isEqual:@"github.com"] && [url.path hasPrefix:@"/Watertube-bilibili/wxfilehelper-macos/releases/"]) {
        [NSWorkspace.sharedWorkspace openURL:url];
    }
}
- (void)about:(id)sender {
    [NSApp orderFrontStandardAboutPanelWithOptions:@{NSAboutPanelOptionApplicationName:@"WX FileHelper",
        NSAboutPanelOptionCredits:[[NSAttributedString alloc] initWithString:@"独立开源项目 · AGPL-3.0-only\nIndependent project, unaffiliated with Tencent."]}];
}
- (BOOL)validateMenuItem:(NSMenuItem *)item {
    SEL a = item.action;
    if (a == @selector(pick:)) return self.attach.enabled;
    if (a == @selector(sendNow:)) return self.send.enabled;
    if (a == @selector(saveSelected:)) return self.save.enabled;
    if (a == @selector(addTab:)) return self.tabs.segmentCount < 2;
    if (a == @selector(closeTab:) || a == @selector(nextTab:)) return self.tabs.segmentCount > 1;
    if (a == @selector(signOut:)) return [self.account[@"SignedIn"] boolValue];
    if (a == @selector(openRelease:)) return [self.state[@"Update"] isKindOfClass:NSDictionary.class];
    return YES;
}
@end

int wxRunMac(int smoke) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:smoke ? NSApplicationActivationPolicyAccessory : NSApplicationActivationPolicyRegular];
        __attribute__((objc_precise_lifetime)) WXMac *delegate = [WXMac new]; delegate.smoke = smoke != 0;
        if (smoke) {
            [app finishLaunching]; [delegate buildWindow];
            NSNumber *first = delegate.active;
            if ([delegate.tabs segmentCount] != 1 || delegate.send.enabled || !first || delegate.refreshQR.hidden) return 1;
            [delegate addTab:nil]; NSNumber *second = delegate.active;
            if ([delegate.tabs segmentCount] != 2 || [first isEqual:second]) return 1;
            [delegate nextTab:nil]; if (![delegate.active isEqual:first]) return 1;
            [delegate.window setContentSize:NSMakeSize(560,400)]; [delegate layout]; if (!delegate.rail.hidden) return 1;
            [delegate.window setContentSize:NSMakeSize(960,660)]; [delegate layout]; if (delegate.rail.hidden) return 1;
            if (NSMaxX(delegate.refreshQR.frame)>NSWidth(delegate.root.bounds) || NSMaxY(delegate.refreshQR.frame)>NSHeight(delegate.root.bounds)) return 1;
            // Exercise the real transfer controls without signing in to a personal account.
            NSDictionary *online = @{@"ID":first,@"DraftEpoch":@0,@"SignedIn":@YES,@"Name":@"Smoke test",@"Status":@"online",
                @"Files":@[@{@"Name":@"lesson.pdf",@"Path":@"/tmp/lesson.pdf",@"Size":@1024}],
                @"Messages":@[@{@"ID":@"smoke-attachment",@"Text":@"lesson.pdf",@"Kind":@"file",@"CanSave":@YES,@"Size":@1024,@"Timestamp":@1}]};
            [delegate applySnapshot:@{@"Accounts":@[online],@"Active":first,@"Revision":@900}];
            [delegate.history selectRowIndexes:[NSIndexSet indexSetWithIndex:0] byExtendingSelection:NO];
            [delegate updateButtons];
            if (delegate.qr.hidden == NO || delegate.queuePane.hidden || delegate.rows.count != 1 || !delegate.send.enabled || !delegate.save.enabled) return 1;
            if (![[delegate.tabs labelForSegment:0] containsString:@"Smoke test"]) return 1;
            return 0;
        }
        app.delegate = delegate; [app run]; return 0;
    }
}
