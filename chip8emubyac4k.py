import pygame
import random
import sys
import platform
import subprocess

import tkinter as tk
from tkinter import messagebox, filedialog

# macOS: never call tk.Tk() after pygame/SDL — it crashes with
# NSInvalidArgumentException (SDLApplication macOSVersion). Use osascript instead.
_TK_ROOT = None


def _is_darwin() -> bool:
    return platform.system() == "Darwin"


def _apple_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _macos_pick_rom_path() -> str | None:
    """Native file picker; returns POSIX path or None if cancelled / error."""
    script = 'POSIX path of (choose file with prompt "Select CHIP-8 ROM")'
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    path = (r.stdout or "").strip()
    return path or None


def _macos_show_alert(title: str, body: str) -> None:
    """Native informational alert (no Tk)."""
    body_flat = " ".join(line.strip() for line in body.splitlines() if line.strip())
    if len(body_flat) > 450:
        body_flat = body_flat[:447] + "..."
    t = _apple_escape(title)
    b = _apple_escape(body_flat)
    script = f'display alert "{t}" message "{b}" as informational'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=60)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass


def _ensure_tk_root() -> tk.Tk:
    """Single hidden Tk; only use on non-macOS (after pygame is OK there)."""
    global _TK_ROOT
    if _TK_ROOT is None:
        _TK_ROOT = tk.Tk()
        _TK_ROOT.withdraw()
        _TK_ROOT.update_idletasks()
    return _TK_ROOT


# ===========================================================
# AC'S CHIP-8 EMULATOR v0.1
# ===========================================================

class Chip8:
    def __init__(self):
        self._rom_cache = None
        self.font_data = [
            0xF0,0x90,0x90,0x90,0xF0, 0x20,0x60,0x20,0x20,0x70, 0xF0,0x10,0xF0,0x80,0xF0,
            0xF0,0x10,0xF0,0x10,0xF0, 0x90,0x90,0xF0,0x10,0x10, 0xF0,0x80,0xF0,0x10,0xF0,
            0xF0,0x80,0xF0,0x90,0xF0, 0xF0,0x10,0x20,0x40,0x40, 0xF0,0x90,0xF0,0x90,0xF0,
            0xF0,0x90,0xF0,0x10,0xF0, 0xF0,0x90,0xF0,0x90,0x90, 0xE0,0x90,0xE0,0x90,0xE0,
            0xF0,0x80,0x80,0x80,0xF0, 0xE0,0x90,0x90,0x90,0xE0, 0xF0,0x80,0xF0,0x80,0xF0,
            0xF0,0x80,0xF0,0x80,0x80
        ]
        self.reset()

    def reset(self):
        """Clear CPU/RAM; restore font; re-embed last loaded ROM if any (so menu Reset works)."""
        self.memory = bytearray(4096)
        self.v = bytearray(16)
        self.i = 0
        self.pc = 0x200
        self.stack = []
        self.delay_timer = 0
        self.sound_timer = 0
        self.display = [0] * (64 * 32)
        self.keypad = [0] * 16
        self.draw_flag = True
        for i, b in enumerate(self.font_data):
            self.memory[i] = b
        self.rom_loaded = False
        if self._rom_cache is not None:
            for i in range(len(self._rom_cache)):
                if 0x200 + i < 4096:
                    self.memory[0x200 + i] = self._rom_cache[i]
            self.rom_loaded = True
        self.paused = not self.rom_loaded

    def load_rom(self, data: bytes):
        self._rom_cache = bytes(data)
        self.reset()
        self.paused = False

    def cycle(self):
        if self.paused or not self.rom_loaded: return
        try:
            opcode = (self.memory[self.pc]<<8)|self.memory[self.pc+1]
            self.pc += 2
        except IndexError:
            self.paused = True
            return

        x = (opcode & 0x0F00) >> 8
        y = (opcode & 0x00F0) >> 4
        n = opcode & 0x000F
        nn = opcode & 0x00FF
        nnn = opcode & 0x0FFF
        prefix = opcode >> 12

        if prefix==0x0:
            if nn==0xE0: self.display=[0]*(64*32); self.draw_flag=True
            elif nn==0xEE: self.pc=self.stack.pop() if self.stack else self.pc
        elif prefix==0x1: self.pc=nnn
        elif prefix==0x2: self.stack.append(self.pc); self.pc=nnn
        elif prefix==0x3: self.pc+=2 if self.v[x]==nn else 0
        elif prefix==0x4: self.pc+=2 if self.v[x]!=nn else 0
        elif prefix==0x5: self.pc+=2 if self.v[x]==self.v[y] else 0
        elif prefix==0x6: self.v[x]=nn
        elif prefix==0x7: self.v[x]=(self.v[x]+nn)&0xFF
        elif prefix==0x8:
            if n==0x0: self.v[x]=self.v[y]
            elif n==0x1: self.v[x]|=self.v[y]
            elif n==0x2: self.v[x]&=self.v[y]
            elif n==0x3: self.v[x]^=self.v[y]
            elif n==0x4: r=self.v[x]+self.v[y]; self.v[0xF]=1 if r>255 else 0; self.v[x]=r&0xFF
            elif n==0x5: self.v[0xF]=1 if self.v[x]>self.v[y] else 0; self.v[x]=(self.v[x]-self.v[y])&0xFF
            elif n==0x6: self.v[0xF]=self.v[x]&1; self.v[x]>>=1
            elif n==0x7: self.v[0xF]=1 if self.v[y]>self.v[x] else 0; self.v[x]=(self.v[y]-self.v[x])&0xFF
            elif n==0xE: self.v[0xF]=(self.v[x]&0x80)>>7; self.v[x]=(self.v[x]<<1)&0xFF
        elif prefix==0x9: self.pc+=2 if self.v[x]!=self.v[y] else 0
        elif prefix==0xA: self.i=nnn
        elif prefix==0xB: self.pc=nnn+self.v[0]
        elif prefix==0xC: self.v[x]=random.randint(0,255)&nn
        elif prefix==0xD:
            vx,vy=self.v[x],self.v[y]; self.v[0xF]=0
            for row in range(n):
                pixel=self.memory[self.i+row]
                for col in range(8):
                    if pixel & (0x80>>col):
                        idx=((vx+col)%64)+((vy+row)%32)*64
                        if self.display[idx]: self.v[0xF]=1
                        self.display[idx]^=1
            self.draw_flag=True
        elif prefix==0xE:
            if nn==0x9E: self.pc+=2 if self.keypad[self.v[x]] else 0
            elif nn==0xA1: self.pc+=2 if not self.keypad[self.v[x]] else 0
        elif prefix==0xF:
            if nn==0x07: self.v[x]=self.delay_timer
            elif nn==0x0A:
                key_pressed=False
                for i in range(16):
                    if self.keypad[i]: self.v[x]=i; key_pressed=True
                if not key_pressed: self.pc-=2
            elif nn==0x15: self.delay_timer=self.v[x]
            elif nn==0x18: self.sound_timer=self.v[x]
            elif nn==0x1E: self.i=(self.i+self.v[x])&0xFFF
            elif nn==0x29: self.i=self.v[x]*5
            elif nn==0x33:
                val=self.v[x]
                self.memory[self.i]=val//100
                self.memory[self.i+1]=(val//10)%10
                self.memory[self.i+2]=val%10
            elif nn==0x55: 
                for j in range(x+1): self.memory[self.i+j]=self.v[j]
            elif nn==0x65: 
                for j in range(x+1): self.v[j]=self.memory[self.i+j]

    def update_timers(self):
        if self.delay_timer>0: self.delay_timer-=1
        if self.sound_timer>0: self.sound_timer-=1

# ===========================================================
# GUI
# ===========================================================

class EmulatorGUI:
    DROPDOWN_WIDTH = 176
    ITEM_HEIGHT = 26
    MENU_ORDER = ("File", "Emulator", "Help")

    def __init__(self, chip8):
        if not _is_darwin():
            _ensure_tk_root()
        pygame.init()
        self.chip8 = chip8
        self.scale = 12
        self.menu_height = 30
        self.footer_height = 28

        self.width = 64 * self.scale
        self.height = 32 * self.scale + self.menu_height + self.footer_height
        self.screen = pygame.display.set_mode((self.width, self.height))
        # Updated window caption
        pygame.display.set_caption("AC'S Chip 8 emulator 0.1")

        self.menu_font = pygame.font.SysFont("Segoe UI", 15, bold=True)
        self.small_font = pygame.font.SysFont("Segoe UI", 12)
        self.tiny_font = pygame.font.SysFont("Consolas", 11)

        self.colors = {
            "window": (32, 28, 52),
            "bezel_top": (48, 42, 78),
            "bezel_bottom": (40, 34, 64),
            "crt_bg": (16, 12, 28),
            "pixel": (255, 210, 128),
            "pixel_glow": (120, 80, 140),
            "menu_bar": (62, 54, 98),
            "menu_hi": (88, 76, 140),
            "menu_text": (245, 238, 255),
            "menu_accent": (255, 160, 200),
            "dropdown_bg": (42, 36, 68),
            "dropdown_hi": (130, 90, 180),
            "dropdown_border": (100, 86, 150),
            "footer_bg": (28, 24, 44),
            "footer_text": (180, 170, 210),
        }

        self.active_menu = None
        self.menu_rects = {}

        self.menus = {
            "File": [("Load ROM…", self.open_rom), ("Exit", self.quit_app)],
            "Emulator": [("Pause / Resume", self.toggle_pause), ("Reset", self._reset_emulator)],
            "Help": [("Controls", self.show_controls), ("About", self.show_about)],
        }

        # Keep top-left tag out of menu hitboxes (was stealing clicks from File).
        # Updated the tag to match the requested title
        tag_w = self.small_font.render("AC'S Chip 8 emulator 0.1", True, self.colors["menu_accent"]).get_width()
        self._menus_start_x = max(10, 8 + tag_w + 14)
        x_offset = self._menus_start_x
        for name in self.MENU_ORDER:
            txt = self.menu_font.render(name, True, self.colors["menu_text"])
            hitbox = pygame.Rect(x_offset, 0, txt.get_width() + 20, self.menu_height)
            self.menu_rects[name] = hitbox
            x_offset += hitbox.width + 4

        self._playfield_top = self.menu_height
        self._playfield_h = 32 * self.scale
        self._scanline_surf = pygame.Surface((self.width, self._playfield_h), pygame.SRCALPHA)
        for ly in range(0, self._playfield_h, 2):
            pygame.draw.line(self._scanline_surf, (0, 0, 0, 28), (0, ly), (self.width, ly))

    def _pump_pygame(self):
        pygame.event.pump()

    def _reset_emulator(self):
        self.chip8.reset()
        if self.chip8.rom_loaded:
            self.chip8.paused = False

    def quit_app(self):
        pygame.quit()
        sys.exit()

    def toggle_pause(self):
        if self.chip8.rom_loaded:
            self.chip8.paused = not self.chip8.paused

    def open_rom(self):
        was_paused = self.chip8.paused
        self.chip8.paused = True
        if _is_darwin():
            path = _macos_pick_rom_path()
        else:
            root = _ensure_tk_root()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                parent=root,
                title="Select CHIP-8 ROM",
                filetypes=[("CHIP-8 files", "*.ch8"), ("All files", "*.*")],
            )
        self._pump_pygame()
        if path:
            try:
                with open(path, "rb") as f:
                    self.chip8.load_rom(f.read())
            except Exception as e:
                print(f"Error loading ROM: {e}")
                self.chip8.paused = was_paused
        else:
            self.chip8.paused = was_paused

    def show_controls(self):
        was_paused = self.chip8.paused
        self.chip8.paused = True
        msg = (
            "Keypad (COSMAC layout)\n\n"
            "1 2 3 4  →  1 2 3 C\n"
            "Q W E R  →  4 5 6 D\n"
            "A S D F  →  7 8 9 E\n"
            "Z X C V  →  A 0 B F\n\n"
            "Space — pause / resume when a ROM is loaded :3"
        )
        if _is_darwin():
            _macos_show_alert("Controls", msg)
        else:
            root = _ensure_tk_root()
            root.attributes("-topmost", True)
            messagebox.showinfo("Controls", msg, parent=root)
        self._pump_pygame()
        self.chip8.paused = was_paused

    def show_about(self):
        was_paused = self.chip8.paused
        self.chip8.paused = True
        about_msg = (
            "AC'S CHIP-8 Emulator v0.1\n\n"
            "Little interpreter, big cozy vibes.\n"
            "(C) AC HOLDINGS 2026\n\n"
            "Python + pygame + love ≽ܫ≼"
        )
        if _is_darwin():
            _macos_show_alert("About", about_msg)
        else:
            root = _ensure_tk_root()
            root.attributes("-topmost", True)
            messagebox.showinfo("About", about_msg, parent=root)
        self._pump_pygame()
        self.chip8.paused = was_paused

    def _dropdown_layout(self):
        """Open dropdown position + size (clamped to window; wide enough for labels)."""
        if not self.active_menu:
            return None
        parent = self.menu_rects[self.active_menu]
        items = self.menus[self.active_menu]
        margin = 6
        w = self.DROPDOWN_WIDTH
        for label, _ in items:
            w = max(w, self.menu_font.render(label, True, self.colors["menu_text"]).get_width() + 36)
        w = min(w, self.width - 2 * margin)
        x = parent.x
        if x + w > self.width - margin:
            x = self.width - margin - w
        x = max(margin, x)
        dh = len(items) * self.ITEM_HEIGHT
        y = parent.bottom
        footer_top = self.menu_height + self._playfield_h
        if y + dh > footer_top:
            y = max(parent.bottom, footer_top - dh)
        return x, y, w, dh

    def _dropdown_panel_rect(self):
        lay = self._dropdown_layout()
        if not lay:
            return None
        x, y, w, dh = lay
        return pygame.Rect(x, y, w, dh)

    def _dropdown_item_rows(self):
        """Rects for each open dropdown row (same geometry as draw)."""
        lay = self._dropdown_layout()
        if not lay:
            return []
        x, y, w, _dh = lay
        rows = []
        for i, (label, action) in enumerate(self.menus[self.active_menu]):
            r = pygame.Rect(x, y + i * self.ITEM_HEIGHT, w, self.ITEM_HEIGHT)
            rows.append((r, action, label))
        return rows

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit_app()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                panel = self._dropdown_panel_rect()

                if self.active_menu and panel and panel.collidepoint(mx, my):
                    hit = False
                    for rect, action, _label in self._dropdown_item_rows():
                        if rect.collidepoint(mx, my):
                            self.active_menu = None
                            action()
                            hit = True
                            break
                    if hit:
                        continue
                    self.active_menu = None
                    continue

                clicked_header = False
                for name in self.MENU_ORDER:
                    rect = self.menu_rects[name]
                    if rect.collidepoint(mx, my):
                        self.active_menu = None if self.active_menu == name else name
                        clicked_header = True
                        break
                if clicked_header:
                    continue

                if self.active_menu:
                    self.active_menu = None

            elif event.type == pygame.KEYDOWN:
                if self.active_menu:
                    self.active_menu = None
                    # Do not pass keys to CHIP-8 while / after dismissing the menu strip.
                    continue

                if event.key == pygame.K_SPACE:
                    self.toggle_pause()

                keys_map = {
                    pygame.K_1: 0x1,
                    pygame.K_2: 0x2,
                    pygame.K_3: 0x3,
                    pygame.K_4: 0xC,
                    pygame.K_q: 0x4,
                    pygame.K_w: 0x5,
                    pygame.K_e: 0x6,
                    pygame.K_r: 0xD,
                    pygame.K_a: 0x7,
                    pygame.K_s: 0x8,
                    pygame.K_d: 0x9,
                    pygame.K_f: 0xE,
                    pygame.K_z: 0xA,
                    pygame.K_x: 0x0,
                    pygame.K_c: 0xB,
                    pygame.K_v: 0xF,
                }
                if event.key in keys_map:
                    self.chip8.keypad[keys_map[event.key]] = 1

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                if self.active_menu:
                    self.active_menu = None

            elif event.type == pygame.KEYUP:
                keys_map = {
                    pygame.K_1: 0x1,
                    pygame.K_2: 0x2,
                    pygame.K_3: 0x3,
                    pygame.K_4: 0xC,
                    pygame.K_q: 0x4,
                    pygame.K_w: 0x5,
                    pygame.K_e: 0x6,
                    pygame.K_r: 0xD,
                    pygame.K_a: 0x7,
                    pygame.K_s: 0x8,
                    pygame.K_d: 0x9,
                    pygame.K_f: 0xE,
                    pygame.K_z: 0xA,
                    pygame.K_x: 0x0,
                    pygame.K_c: 0xB,
                    pygame.K_v: 0xF,
                }
                if event.key in keys_map:
                    self.chip8.keypad[keys_map[event.key]] = 0

    def draw_menustrip(self):
        bar = pygame.Rect(0, 0, self.width, self.menu_height)
        pygame.draw.rect(self.screen, self.colors["menu_bar"], bar)
        pygame.draw.line(self.screen, self.colors["bezel_top"], (0, self.menu_height - 1), (self.width, self.menu_height - 1))

        # Updated title rendering
        tag = self.small_font.render("AC'S Chip 8 emulator 0.1", True, self.colors["menu_accent"])
        self.screen.blit(tag, (10, self.menu_height - tag.get_height() - 3))

        if self.chip8.rom_loaded:
            status = "running" if not self.chip8.paused else "paused"
            color = (160, 255, 190) if not self.chip8.paused else (255, 170, 200)
        else:
            status = "no rom"
            color = (200, 190, 220)
        txt_status = self.menu_font.render(status, True, color)
        self.screen.blit(
            txt_status,
            (self.width - txt_status.get_width() - 12, (self.menu_height - txt_status.get_height()) // 2),
        )

        mouse_pos = pygame.mouse.get_pos()
        for name in self.MENU_ORDER:
            rect = self.menu_rects[name]
            # While a dropdown is open, only highlight its parent header (no hover-switching).
            hi = self.active_menu == name or (
                not self.active_menu and rect.collidepoint(mouse_pos)
            )
            if hi:
                pygame.draw.rect(self.screen, self.colors["menu_hi"], rect, border_radius=6)
            txt = self.menu_font.render(name, True, self.colors["menu_text"])
            self.screen.blit(txt, (rect.x + 10, (self.menu_height - txt.get_height()) // 2))

    def draw_dropdown(self):
        if not self.active_menu:
            return

        lay = self._dropdown_layout()
        if not lay:
            return
        dx, dy, dw, dh = lay
        ih = self.ITEM_HEIGHT
        dropdown_bg_rect = pygame.Rect(dx, dy, dw, dh)

        shadow = pygame.Surface((dw, dh), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 90))
        self.screen.blit(shadow, (dropdown_bg_rect.x + 3, dropdown_bg_rect.y + 4))

        pygame.draw.rect(self.screen, self.colors["dropdown_bg"], dropdown_bg_rect, border_radius=4)
        pygame.draw.rect(self.screen, self.colors["dropdown_border"], dropdown_bg_rect, 1, border_radius=4)

        mouse_pos = pygame.mouse.get_pos()
        for item_rect, _action, label in self._dropdown_item_rows():
            if item_rect.collidepoint(mouse_pos):
                pygame.draw.rect(self.screen, self.colors["dropdown_hi"], item_rect)
            txt = self.menu_font.render(label, True, self.colors["menu_text"])
            self.screen.blit(txt, (item_rect.x + 12, item_rect.y + (ih - txt.get_height()) // 2))

    def draw_footer(self):
        y0 = self.menu_height + self._playfield_h
        foot = pygame.Rect(0, y0, self.width, self.footer_height)
        pygame.draw.rect(self.screen, self.colors["footer_bg"], foot)
        pygame.draw.line(self.screen, self.colors["bezel_bottom"], (0, y0), (self.width, y0))
        hint = (
            "keys: 1-4 / QWER / ASDF / ZXCV  ·  Space: pause  ·  "
            "File → Load ROM…  ·  meow :3"
        )
        t = self.tiny_font.render(hint, True, self.colors["footer_text"])
        self.screen.blit(t, (10, y0 + (self.footer_height - t.get_height()) // 2))

    def draw(self):
        self.screen.fill(self.colors["window"])

        pf = pygame.Rect(0, self._playfield_top, self.width, self._playfield_h)
        pygame.draw.rect(self.screen, self.colors["bezel_top"], pf)
        inner = pf.inflate(-10, -10)
        pygame.draw.rect(self.screen, self.colors["crt_bg"], inner)

        ox = inner.x
        oy = inner.y
        gw = inner.width // 64
        gh = inner.height // 32
        g = max(1, min(gw, gh))
        tw, th = 64 * g, 32 * g
        bx = ox + (inner.width - tw) // 2
        by = oy + (inner.height - th) // 2

        for yy in range(32):
            for xx in range(64):
                if self.chip8.display[xx + yy * 64]:
                    px = bx + xx * g
                    py = by + yy * g
                    pygame.draw.rect(self.screen, self.colors["pixel_glow"], (px, py, g, g))
                    inset = 1 if g > 2 else 0
                    pygame.draw.rect(
                        self.screen,
                        self.colors["pixel"],
                        (px + inset, py + inset, g - 2 * inset, g - 2 * inset),
                    )

        self.screen.blit(self._scanline_surf, (0, self._playfield_top))

        self.draw_menustrip()
        self.draw_dropdown()
        self.draw_footer()

        pygame.display.flip()

    def run(self):
        clock = pygame.time.Clock()
        while True:
            self.handle_input()
            if not self.chip8.paused:
                for _ in range(10):
                    self.chip8.cycle()
                self.chip8.update_timers()
            self.draw()
            clock.tick(60)

# ===========================================================
# MAIN
# ===========================================================

if __name__ == "__main__":
    chip8 = Chip8()
    gui = EmulatorGUI(chip8)
    gui.run()