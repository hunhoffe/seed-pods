import 'jquery-ui/themes/base/resizable.css';
import 'bootstrap-icons/font/bootstrap-icons.css';

import $ from 'jquery';

import 'jquery-ui';
import 'jquery-ui/ui/widgets/resizable';

import { ConsoleEvent } from './console-event';

// todo: windows, etc?
export type WindowManagerEvent = 'taskbarchanges';

export class Window {
    private _id: string;
    private _title: string;
    private _statusText: string;
    private _element: HTMLDivElement;
    private _titleElement: HTMLSpanElement;
    private _frameElement: HTMLIFrameElement;
    private _manager: WindowManager;

    private _maskElement: HTMLDivElement;
    private _titleBarElement: HTMLDivElement;
    private _x: number;
    private _y: number;
    private _dx: number;
    private _dy: number;
    private _dragging: boolean;

    private _bondedMoveHandler: any;
    private _bondedDownHandler: any;
    private _bondedUpHandler: any;

    private _inSynth: boolean;
    private _synthControlElement: Element;

    constructor(manager: WindowManager, id: string, title: string, url: string, top: number, left: number) {
        this._manager = manager;
        this._dragging = false;
        this._inSynth = false;

        var console = document.createElement('div');
        var titleBar = document.createElement('div');
        var titleText = document.createElement('span');
        var titleActions = document.createElement('span');
        var consoleMask = document.createElement('div');
        var consoleFrame = document.createElement('iframe');

        consoleFrame.setAttribute('container-id', id);

        this._id = id;
        this._title = title;
        this._element = console;
        this._frameElement = consoleFrame;
        this._titleElement = titleText;

        this.setStatusText('(connecting...)');

        titleText.className = 'console-title';
        titleText.innerText = title;

        titleBar.className = 'console-titlebar';

        var iClose = document.createElement('i');
        iClose.className = 'bi bi-x-circle console-action';
        iClose.onclick = this.close.bind(this);
        iClose.title = 'Close';

        var iMin = document.createElement('i');
        iMin.className = 'bi bi-box-arrow-in-down-left console-action';
        iMin.onclick = this.minimize.bind(this);
        iMin.title = 'Minimize'

        var iMax = document.createElement('i');
        iMax.className = 'bi bi-box-arrow-up-right console-action';
        iMax.onclick = this.popOut.bind(this);
        iMax.title = 'Open in new window';

        var iReload = document.createElement('i');
        iReload.className = 'bi bi-bootstrap-reboot console-action';
        iReload.onclick = this.reload.bind(this);
        iReload.title = 'Reload terminal';

        var iSynth = document.createElement('i');
        iSynth.className = 'bi bi-keyboard console-action';
        iSynth.onclick = this.toggleSynth.bind(this);
        iSynth.title = 'Add this session to input broadcast';
        this._synthControlElement = iSynth;

        titleActions.className = 'console-actions';
        titleActions.appendChild(iClose);
        titleActions.appendChild(iMin);
        titleActions.appendChild(iMax);
        titleActions.appendChild(iReload);
        titleActions.appendChild(iSynth);

        titleBar.appendChild(titleActions);
        titleBar.appendChild(titleText);
        console.appendChild(titleBar);

        consoleFrame.src = url;
        consoleFrame.className = 'console';
        console.appendChild(consoleFrame);

        consoleMask.className = 'console mask hide';
        console.appendChild(consoleMask);

        console.className = 'console-window';

        var jconsole = $(console);

        jconsole.resizable({
            minHeight: 45,
            minWidth: 125
        });

        jconsole.offset({ top, left });

        this._titleBarElement = titleBar;
        this._maskElement = consoleMask;

        this._bondedDownHandler = this._handleDragStart.bind(this);
        this._bondedUpHandler = this._handleDragEnd.bind(this);
        this._bondedMoveHandler = this._handleDragMove.bind(this);

        this._element.addEventListener('mousedown', this._bondedDownHandler);
        this._element.addEventListener('mouseup', this._bondedUpHandler);
    }

    getId(): string {
        return this._id;
    }

    getTitle(): string {
        return this._title;
    }

    setTitle(newTitle: string) {
        this._title = newTitle;
        this._titleElement.innerText = `${newTitle} ${this._statusText}`;
    }

    getStatusText(): string {
        return this._statusText;
    }

    setStatusText(status: string) {
        this._statusText = status;
        this._titleElement.innerText = `${this._title} ${status}`;
    }

    block() {
        this._maskElement.classList.remove('hide');
    }

    unblock() {
        this._maskElement.classList.add('hide');
    }

    getElement(): Element {
        return this._element;
    }

    close() {
        this._manager.closeWindow(this._id);
        document.removeEventListener('mousemove', this._bondedMoveHandler);
    }

    popOut() {
        var h = this._frameElement.clientHeight;
        var w = this._frameElement.clientWidth;

        this.close();
        window.open(
            `/console.html#${this._id}`, this._title,
            `directories=no,titlebar=no,toolbar=no,location=no,status=no,menubar=no,scrollbars=no,width=${w},height=${h}`);
    }

    minimize() {
        this._titleBarElement.classList.remove('active');
        this._manager.minimizeWindow(this);
    }

    reload() {
        this.setStatusText('(connecting...)');
        this._frameElement.contentWindow.location.reload();
    }

    toBack() {
        this._titleBarElement.classList.remove('active');
    }

    toFront() {
        this._manager.setActiveWindow(this);
        this._titleBarElement.classList.add('active');
    }

    isInSynth(): boolean {
        return this._inSynth;
    }

    toggleSynth() {
        if (this._inSynth) {
            this._inSynth = false;
            this._synthControlElement.className = 'bi bi-keyboard console-action';
        } else {
            this._inSynth = true;
            this._synthControlElement.className = 'bi bi-keyboard-fill console-action';
        }
    }

    write(data: any) {
        this._frameElement.contentWindow.document.dispatchEvent(new CustomEvent<ConsoleEvent>('console', {
            detail: {
                type: 'data',
                id: this._id,
                data
            }
        }));
    }

    private _handleDragStart(e: MouseEvent) {
        this._manager.blockWindows();

        if (e.button != 0) return;

        var target = e.target as Element;

        if (target != this._titleBarElement && target.parentElement != this._titleBarElement) return; 

        this._element.classList.add('dragging');

        if (this._dragging) return;

        this.toFront();
        this._dragging = true;
        this._x = e.pageX;
        this._y = e.pageY;

        document.addEventListener('mousemove', this._bondedMoveHandler);
    }

    private _handleDragEnd(e: MouseEvent) {
        this._manager.unblockWindows();

        this._element.classList.remove('dragging');
        if (!this._dragging) return;
        this._dragging = false;

        document.removeEventListener('mousemove', this._bondedMoveHandler);
    }

    private _handleDragMove(e: MouseEvent) {
        if (!this._dragging) return;

        this._dy = e.pageY - this._y;
        this._dx = e.pageX - this._x;

        var offset = $(this._element).offset();
        $(this._element).offset({
            left: offset.left + this._dx,
            top: offset.top + this._dy
        });

        this._x = e.pageX;
        this._y = e.pageY;
    }
};

export class WindowManager {
    private _windows: {
        [id: string]: Window
    };

    private _desktop: HTMLDivElement;
    private _taskbar: HTMLDivElement;
    private _zindex: number;
    private _nextOffset: number;
    private _activeWindowId: string;

    private _taskBarChangeEventHandler: (shown: boolean) => void;

    constructor(desktopElement: string, taskbarElement: string) {
        this._windows = {};
        this._desktop = document.getElementById(desktopElement) as HTMLDivElement;
        this._taskbar = document.getElementById(taskbarElement) as HTMLDivElement;
        this._zindex = 10000;
        this._nextOffset = 0;

        var ceHandler = this._consoleEventListener.bind(this);
        var ksHandler = this._keyboardEventListener.bind(this);

        document.addEventListener('console', (e: CustomEvent<ConsoleEvent>) => {
            ceHandler(e.detail);
        });

        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.altKey || e.metaKey) {
                ksHandler(e);
            }
        });
    }

    on(event: WindowManagerEvent, handler: (event: any) => void) {
        if (event == 'taskbarchanges') {
            this._taskBarChangeEventHandler = handler;
        }
    }

    private _broadcastInput(srcId: string, data: any) {
        Object.keys(this._windows).forEach(wid => {
            if (wid == srcId) return;
            
            var win = this._windows[wid];
            if (win.isInSynth()) {
                win.write(data);
            }
        });
    }

    private _procressKeyboardEvent(e: KeyboardEvent, win?: Window): boolean {
        if (e.type != 'keydown') return;

        if (e.ctrlKey && e.altKey) {
            switch (e.code) {
                case 'KeyW':
                    win?.close();
                    return true;
                case 'KeyS':
                    if (win) this.minimizeWindow(win);
                    return true;
                case 'KeyE':
                    win?.toggleSynth();
                    return true;
                case 'KeyF':
                    win?.popOut();
                    return true;
                case 'KeyR':
                    win?.reload();
                    return true;
                case 'KeyD':
                    Object.keys(this._windows).forEach(w => {
                        this._windows[w].minimize();
                    });
                    return true;
                case 'KeyA':
                    var keys = Object.keys(this._windows);
                    var allInSynth = true;

                    keys.forEach(k => {
                        allInSynth &&= this._windows[k].isInSynth();
                    });

                    if (allInSynth) {
                        keys.forEach(k => this._windows[k].toggleSynth());
                    } else {
                        keys.forEach(k => {
                            if (!this._windows[k].isInSynth()) this._windows[k].toggleSynth();
                        });
                    }
            }
        }

        return false;
    }

    private _keyboardEventListener(e: KeyboardEvent, sourceId?: string) {
        if (!sourceId) sourceId = this._activeWindowId;

        if (this._procressKeyboardEvent(e, this._windows[sourceId])) {
            e.preventDefault();
            e.stopPropagation();
        }
    }

    private _consoleEventListener(ce: ConsoleEvent) {
        if (!this._windows[ce.id]) return;
        var win = this._windows[ce.id];

        switch(ce.type) {
            case 'ready':
                win.setStatusText('');
            case 'focus': 
                win.toFront();
                break;
            case 'blur':
                break;
            case 'error':
                win.setStatusText(`(inactive: error)`);
                break;
            case 'closed':
                win.setStatusText(`(inactive: disconnected)`);
                break;
            case 'data':
                if (win.isInSynth()) {
                    this._broadcastInput(ce.id, ce.data);
                }
                break;
            case 'rawkey':
                var k = ce.data as KeyboardEvent;
                if (k.ctrlKey || k.altKey || k.metaKey) {
                    this._keyboardEventListener(k, ce.id);
                } 
                break;
        }
    }

    private _updateTaskbar() {
        this._taskbar.innerHTML = '';

        Object.keys(this._windows).forEach(wid => {
            var win = this._windows[wid];
            var item = document.createElement('button');
            var text = document.createElement('span');
            
            text.innerText = text.title = win.getTitle();
            text.classList.add('taskbar-item-text');

            item.onclick = () => this._handleTaskbarClick.bind(this)(wid);
            item.classList.add('taskbar-item');
            item.appendChild(text);

            if (wid == this._activeWindowId) item.classList.add('active');

            this._taskbar.appendChild(item);
        });

        if (this._taskbar.children.length == 0) {
            if (this._taskBarChangeEventHandler) {
                this._taskBarChangeEventHandler(false);
            }

            this._taskbar.classList.add('hide');
        } else { 
            if (this._taskBarChangeEventHandler) {
                this._taskBarChangeEventHandler(true);
            }

            this._taskbar.classList.remove('hide');
        }
    }

    private _handleTaskbarClick(id: string) {
        if (this._activeWindowId == id) {
            this._windows[id].minimize();
        } else {
            this._windows[id].toFront();
        }
    }

    getDesktop(): Element {
        return this._desktop;
    }

    closeWindow(id: string) {
        if (this._windows[id]) {
            this._windows[id].getElement().remove();
            delete this._windows[id];
        }

        this._updateTaskbar();
    }

    createWindow(id: string, title: string) {
        if (this._windows[id]) {
            this._windows[id].toFront();
            return;
        }

        var win = new Window(this, id, title, `/console.html#${id}`, 10 + this._nextOffset, 10 + this._nextOffset);
        this._desktop.appendChild(win.getElement());
        this._windows[id] = win;
        win.toFront();

        this._nextOffset += 30;
        this._nextOffset %= 300;

        this._updateTaskbar();
    }

    getWindows(): {
        [id: string]: Window
    } {
        return this._windows;
    }

    blockWindows() {
        Object.keys(this._windows).forEach(wid => {
            this._windows[wid].block();
        });
    }

    unblockWindows() {
        Object.keys(this._windows).forEach(wid => {
            this._windows[wid].unblock();
        });
    }

    setActiveWindow(window: Window) {
        window.getElement().classList.remove('hide');

        var windows = this.getWindows();
        Object.keys(windows).forEach(id => {
            var window = windows[id];
            window.toBack();

            var zindex = Number.parseInt($(window.getElement()).css('z-index')) || this._zindex;
            if (zindex > this._zindex) this._zindex = zindex;
        });
        
        $(window.getElement()).css('z-index', ++this._zindex);

        this._activeWindowId = window.getId();
        this._updateTaskbar();
    }

    minimizeWindow(window: Window) {
        window.getElement().classList.add('hide');

        if (this._activeWindowId == window.getId()) this._activeWindowId = '';

        this._updateTaskbar();
    }

};