# Artemis python port.. Dec, 19, 2025  (completed edition)
# Original Artemis: Berion, NzV, Dnawrkshp (GUI by Berion, code by Dnawrkshp, network by Bucanero)
# Python port: MexrlDev 2025
# Free for anyone to use, mod, edit privatly, publish with credits to original creators.
#
# Every screen, animation and layout constant below is ported from ArtemisPS3-GUI (PSL1GHT/tiny3d):
# a virtual 848x512 canvas, Comfortaa fonts, 128-frame menu animations, sliding side panels.

import gc
import json
import math
import os
import shutil
import sys
import threading
import time
from itertools import islice
import urllib.request
import zipfile

import pygame

import ncl

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
USER_DIR = os.path.join(BASE, "codes")
ONLINE_DIR = os.path.join(BASE, "online_cache")
CFG_FILE = os.path.join(BASE, "artemis_config.json")
EXPORT_FILE = os.path.join(BASE, "artemis_active.txt")
DB_URL = "https://github.com/bucanero/ArtemisPS3/raw/master/docs/cheatdb.zip"

VERSION = "PC 1.0"
VW, VH = 848, 512            # virtual screen (same as the PS3 build)
FPS = 60                     # animations are TIME based (60 'ticks' per second), so they never slow down
_clock = time.perf_counter   # replaceable in tests
DARK = (26, 0, 0)            # 1A0000, the text colour of the original
CREAM = (247, 241, 236)      # F7F1EC
RED = (157, 0, 0)            # 9D0000, error text

MENU_TITLE_OFF = 30
MENU_ICON_OFF = 70
MENU_SPLIT_OFF = 200
MENU_ANI_MAX = 0x80
MENU_MAIN_ICON_WIDTH = 80

# List row geometry measured from the original screenshots (virtual px, relative to the row's y).
# The selector bar is the 22px mark_line drawn AT y; the text's capital letters are centred on ROW_CENTER.
ROW_EM = 16.9                # font em size of list text (matches the original's text width)
ROW_SIZE = ROW_EM / 1.12     # value passed to text()/font() (they multiply by 1.12)
ROW_CENTER = 11.35           # calibrated so measured cap centre = y+10.65, same as the original screenshot
PILL_Y, PILL_H = -3.3, 26.7  # 'once'/'constant' pill: opaque part spans y+0.4 .. y+19.6
PILL_CENTER = 10.0
ARROW_Y, ARROW_W, ARROW_H = 3.4, 10.5, 17.0   # opaque arrow spans y+7.5 .. y+16.7, centred on x=50

M_MAIN, M_USER, M_ONLINE, M_ABOUT, M_OPTIONS, M_CHEATS, M_VIEW, M_OPTPANEL = range(8)

# menu_pad_help from main.c: (button, label) pairs
PAD_HELP = {
    M_MAIN: [],
    M_USER: [("cross", "Select"), ("circle", "Back"), ("triangle", "Filter"), ("square", "Refresh")],
    M_ONLINE: [("cross", "Select"), ("circle", "Back"), ("triangle", "Filter"), ("square", "Refresh")],
    M_ABOUT: [("circle", "Back")],
    M_OPTIONS: [("cross", "Select"), ("circle", "Back")],
    M_CHEATS: [("cross", "Enable"), ("square", "Toggle Mode"), ("triangle", "View Code"), ("circle", "Back")],
    M_VIEW: [("circle", "Back")],
    M_OPTPANEL: [("cross", "Select"), ("circle", "Back")],
}

CONTROLS = [
    ("Arrow keys / mouse wheel", "Move"),
    ("Enter / left click", "Select  (cross)"),
    ("Esc / Backspace / right click", "Back  (circle)"),
    ("Space", "Toggle once/constant, Refresh  (square)"),
    ("T", "View code, Filter  (triangle)"),
    ("Page Up / Page Down", "Jump to previous / next letter  (L1 / R1)"),
    ("F or F11", "Fullscreen / windowed"),
    ("F1", "This help"),
]

OPTION_ROWS = [
    ("Background Music", "bool", "music"),
    ("Sort Cheats", "bool", "sort"),
    ("Menu Animations", "bool", "ani"),
    ("Fullscreen", "bool", "fullscreen"),
    ("Horizontal Margin", "inc", "hmargin"),
    ("Vertical Margin", "inc", "vmargin"),
    ("Update Local Cheats", "call", "update"),
    ("Clear Local Cache", "call", "clear"),
    ("Export Format", "list", "export"),
]
EXPORT_FORMATS = ["Artemis list (.txt)", "NCL file"]


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class App:
    # ------------------------------------------------------------------ setup
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Artemis PS3 - PC port")
        self.opt = dict(music=True, sort=True, ani=True, fullscreen=False,
                        hmargin=0, vmargin=0, export=0)
        self.state = {"act": {}}
        self._rel = {}
        self._vis = {}
        self._fit = {}
        self._rect_cache = {}
        self._cap = {}
        self.load_config()
        # Canvas resolution is chosen once from the desktop size. The window is then scaled by the GPU
        # (pygame.SCALED + vsync), so there is no per-frame CPU resize.
        self.S = self.pick_scale()
        self.cw = int(VW * self.S) // 2 * 2
        self.ch = int(VH * self.S) // 2 * 2
        self.scaled = False
        self.vsync_on = None
        self.flip_times = []
        self.frame_n = 0
        self.set_window(self.opt["fullscreen"])
        self.canvas = pygame.Surface((self.cw, self.ch)).convert()
        self.clock = pygame.time.Clock()
        self.view = (0, 0, self.cw, self.ch)  # screen rect the canvas is shown in
        pygame.key.set_repeat(330, 55)

        self.raw = {}
        if not os.path.isdir(DATA):
            print(f"[artemis] ERROR: data/ not found at {DATA}")
        else:
            for fn in sorted(os.listdir(DATA)):
                if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    continue
                path = os.path.join(DATA, fn)
                if not os.access(path, os.R_OK):
                    print(f"[artemis] ERROR: cannot read {fn} (permissions)")
                    continue
                try:
                    img = pygame.image.load(path)
                    try:
                        surf = img.convert_alpha()
                    except pygame.error:
                        surf = img
                    if surf.get_width() < 1 or surf.get_height() < 1:
                        print(f"[artemis] WARNING: {fn} is empty")
                        continue
                    self.raw[os.path.splitext(fn)[0]] = surf
                except (pygame.error, OSError) as e:
                    print(f"[artemis] ERROR loading {fn}: {e}")
            print(f"[artemis] Loaded {len(self.raw)} images from data/")
            for req in ("bgimg", "titlescr_logo", "header_line", "mark_line",
                        "mark_arrow", "scroll_bg", "scroll_lock", "cheat"):
                if req not in self.raw:
                    print(f"[artemis] WARNING: required image '{req}' is missing")

        self.tex_cache = {}
        self.font_cache = {}
        self.text_cache = {}

        if "bgimg" in self.raw:
            try:
                self.bg_full = pygame.transform.smoothscale(
                    self.raw["bgimg"], (self.cw, self.ch))
            except (pygame.error, ValueError):
                self.bg_full = pygame.transform.scale(
                    self.raw["bgimg"], (self.cw, self.ch))
            if not (self.bg_full.get_flags() & pygame.SRCALPHA):
                try:
                    self.bg_full = self.bg_full.convert_alpha()
                except pygame.error:
                    pass
        else:
            self.bg_full = pygame.Surface((self.cw, self.ch), pygame.SRCALPHA)
        self.fonts = {
            "regular": os.path.join(DATA, "comfortaa_regular.ttf"),
            "bold": os.path.join(DATA, "comfortaa_bold.ttf"),
            "light": os.path.join(DATA, "comfortaa_light.ttf"),
        }

        # menu state (names follow main.c)
        self.menu_id = M_MAIN
        self.sel = 0
        self.old_sel = [0] * 8
        self.last_menu = [0] * 8
        self.idle_time = 0
        self.progress = 0.0
        self.lists = {M_USER: [], M_ONLINE: []}
        self.filters = {M_USER: "", M_ONLINE: ""}
        self.game = None           # selected Game
        self.game_from = M_USER
        self.option_index = 0
        self.code_for_option = None
        self.mouse_pos = (0, 0)
        self.running = True
        self.typing = False

        self.apply_music()

    # ------------------------------------------------------------- persistence
    def load_config(self):
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.opt.update({k: v for k, v in data.get("options", {}).items() if k in self.opt})
            self.state = {"act": data.get("act", {})}
        except (OSError, ValueError):
            pass

    def save_config(self):
        try:
            with open(CFG_FILE, "w", encoding="utf-8") as f:
                json.dump({"options": self.opt, "act": self.state["act"]}, f, indent=1)
        except OSError:
            pass

    def rel(self, path):
        r = self._rel.get(path)
        if r is None:
            r = self._rel[path] = os.path.relpath(path, BASE).replace("\\", "/")
        return r

    def load_codes(self, game):
        if game.codes is None:
            game.codes = ncl.read_ncl(game.path)
            saved = self.state["act"].get(self.rel(game.path), {})
            for idx, info in saved.items():
                i = int(idx)
                if 0 <= i < len(game.codes):
                    c = game.codes[i]
                    c.activated = True
                    if "cw" in info:
                        c.cwrite = bool(info["cw"])
                    for o, s in zip(c.options, info.get("sel", [])):
                        o.sel = clamp(int(s), 0, max(0, len(o.names) - 1))
        return game.codes

    def persist_game(self, game):
        info = {}
        for i, c in enumerate(game.codes or []):
            if c.activated:
                info[str(i)] = {"cw": c.cwrite, "sel": [o.sel for o in c.options]}
        key = self.rel(game.path)
        if info:
            self.state["act"][key] = info
        else:
            self.state["act"].pop(key, None)
        self.save_config()

    def game_active(self, game):
        return bool(self.state["act"].get(self.rel(game.path)))

    # ------------------------------------------------------------------ audio
    def apply_music(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            if self.opt["music"]:
                if not pygame.mixer.music.get_busy():
                    pygame.mixer.music.load(os.path.join(DATA, "background_music.mp3"))
                    pygame.mixer.music.set_volume(0.5)
                    pygame.mixer.music.play(-1)
            else:
                pygame.mixer.music.stop()
        except Exception:
            pass

    # ----------------------------------------------------------------- window
    def pick_scale(self):
        try:
            info = pygame.display.Info()
            dw, dh = int(info.current_w), int(info.current_h)
        except Exception:
            dw = dh = 0
        if dw <= 0 or dh <= 0:
            dw, dh = 1920, 1080
        return round(clamp(min(dw * 0.92 / VW, dh * 0.86 / VH), 1.25, 2.1) * 20) / 20

    def set_window(self, fullscreen):
        self.scaled = False
        if hasattr(pygame, "SCALED"):
            flags = pygame.SCALED | pygame.RESIZABLE
            if fullscreen:
                flags |= pygame.FULLSCREEN
            try:  # GPU scaling + vsync: smooth, tear free, no CPU resize
                self.screen = pygame.display.set_mode((self.cw, self.ch), flags, vsync=1)
                self.scaled = True
            except Exception:
                self.scaled = False
        if not self.scaled:
            if fullscreen:
                self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.screen = pygame.display.set_mode((self.cw, self.ch), pygame.RESIZABLE)
        self.opt["fullscreen"] = bool(fullscreen)
        self.vsync_on = None
        self.flip_times = []
        self.frame_n = 0

    def toggle_fullscreen(self):
        self.set_window(not self.opt["fullscreen"])
        self.save_config()

    def present(self):
        win = pygame.display.get_surface()
        ww, wh = win.get_size()
        hm, vm = self.opt["hmargin"], self.opt["vmargin"]
        if (ww, wh) == (self.cw, self.ch) and not hm and not vm:
            self.view = (0, 0, ww, wh)
            win.blit(self.canvas, (0, 0))          # 1:1 copy, the GPU does the scaling
        else:                                      # margins / non-scaled fallback
            ax, ay = int(ww * hm / VW), int(wh * vm / VH)
            aw, ah = max(1, ww - 2 * ax), max(1, wh - 2 * ay)
            sc = min(aw / VW, ah / VH)
            dw, dh = max(1, int(VW * sc)), max(1, int(VH * sc))
            dx, dy = ax + (aw - dw) // 2, ay + (ah - dh) // 2
            self.view = (dx, dy, dw, dh)
            win.fill((0, 0, 0))
            win.blit(pygame.transform.smoothscale(self.canvas, (dw, dh)), (dx, dy))
        t = _clock()
        pygame.display.flip()
        return _clock() - t

    def to_virtual(self, pos):
        dx, dy, dw, dh = self.view
        return ((pos[0] - dx) * VW / max(1, dw), (pos[1] - dy) * VH / max(1, dh))

    # ---------------------------------------------------------------- drawing
    def tex(self, name, w, h):
        S = self.S
        w, h = max(1, int(w * S)), max(1, int(h * S))
        key = (name, w, h)
        t = self.tex_cache.get(key)
        if t is not None:
            return t
        if len(self.tex_cache) > 400:
            self.tex_cache.clear()
        src = self.raw.get(name)
        if src is None:
            print(f"[artemis] WARNING: image '{name}' not found in data/")
            t = pygame.Surface((w, h), pygame.SRCALPHA)
            self.tex_cache[key] = t
            return t
        try:
            t = pygame.transform.smoothscale(src, (w, h))
        except (pygame.error, ValueError):
            try:
                t = pygame.transform.scale(src, (w, h))
            except pygame.error:
                t = pygame.Surface((w, h), pygame.SRCALPHA)
        if not (t.get_flags() & pygame.SRCALPHA):
            try:
                t = t.convert_alpha()
            except pygame.error:
                pass
        self.tex_cache[key] = t
        return t

    def draw(self, name, x, y, w, h, a=255):
        if a <= 0:
            return
        t = self.tex(name, w, h)
        px, py = int(x * self.S), int(y * self.S)
        if a >= 255:
            self.canvas.blit(t, (px, py))
        else:
            tmp = t.copy()
            tmp.set_alpha(int(a))
            self.canvas.blit(tmp, (px, py))

    def draw_strip(self, name, x, y, w, h, a=255):
        """Horizontally constant textures (header line, selector bar). One pre-scaled wide strip is cached
        and cropped, so animating the width never triggers a re-scale."""
        if a <= 0 or w <= 0:
            return
        hp = max(1, int(h * self.S))
        key = ("strip", name, hp)
        st = self.tex_cache.get(key)
        if st is None:
            src = self.raw.get(name)
            if src is None:
                print(f"[artemis] WARNING: strip image '{name}' not found in data/")
                st = pygame.Surface((1, hp), pygame.SRCALPHA)
            else:
                try:
                    st = pygame.transform.smoothscale(src, (self.cw + 4, hp))
                except (pygame.error, ValueError):
                    try:
                        st = pygame.transform.scale(src, (self.cw + 4, hp))
                    except pygame.error:
                        st = pygame.Surface((1, hp), pygame.SRCALPHA)
            if not (st.get_flags() & pygame.SRCALPHA):
                try:
                    st = st.convert_alpha()
                except pygame.error:
                    pass
            self.tex_cache[key] = st
        wp = min(st.get_width(), max(1, int(w * self.S)))
        hclamp = min(hp, st.get_height())
        src_rect = pygame.Rect(0, 0, wp, hclamp)
        px, py = int(x * self.S), int(y * self.S)
        if a >= 255:
            self.canvas.blit(st, (px, py), src_rect)
        else:
            tmp = st.copy()
            tmp.set_alpha(int(a))
            self.canvas.blit(tmp, (px, py), src_rect)

    def draw_c(self, name, cx, cy, w, h, a=255):
        self.draw(name, cx - w / 2, cy - h / 2, w, h, a)

    def draw_cx(self, name, cx, y, w, h, a=255):
        self.draw(name, cx - w / 2, y, w, h, a)

    def draw_bg(self, x=0, a=255):
        if a <= 0:
            return
        px = int(x * self.S)
        if px >= self.cw:
            return
        src_rect = pygame.Rect(px, 0, self.cw - px, self.ch)
        if a >= 255:
            self.canvas.blit(self.bg_full, (px, 0), src_rect)
        else:
            tmp = self.bg_full.copy()
            tmp.set_alpha(int(a))
            self.canvas.blit(tmp, (px, 0), src_rect)

    def font(self, face, size):
        key = (face, size)
        f = self.font_cache.get(key)
        if f is None:
            f = pygame.font.Font(self.fonts[face], max(6, int(size * self.S * 1.12)))
            self.font_cache[key] = f
        return f

    def tsurf(self, s, face, size, color, track):
        key = (s, face, size, color, track)
        surf = self.text_cache.get(key)
        if surf is None:
            if len(self.text_cache) > 1500:      # drop the oldest few hundred instead of everything
                for k in list(islice(self.text_cache, 400)):
                    del self.text_cache[k]
            f = self.font(face, size)
            if not track:
                surf = f.render(s, True, color)
                if not (surf.get_flags() & pygame.SRCALPHA):
                    try:
                        surf = surf.convert_alpha()
                    except pygame.error:
                        pass
            else:
                gap = int(track * self.S)
                space = f.size(" ")[0]
                widths = []
                total = 0
                for ch in s:
                    wch = space if ch == " " else f.size(ch)[0]
                    widths.append(wch)
                    total += wch + gap
                surf = pygame.Surface((max(1, total), f.get_height()), pygame.SRCALPHA)
                surf.fill((0, 0, 0, 0))
                x = 0
                for ch, wch in zip(s, widths):
                    if ch != " ":
                        char_surf = f.render(ch, True, color)
                        if not (char_surf.get_flags() & pygame.SRCALPHA):
                            try:
                                char_surf = char_surf.convert_alpha()
                            except pygame.error:
                                pass
                        surf.blit(char_surf, (x, 0))
                    x += wch + gap
            if not (surf.get_flags() & pygame.SRCALPHA):
                try:
                    surf = surf.convert_alpha()
                except pygame.error:
                    pass
            self.text_cache[key] = surf
        return surf

    def text_w(self, s, size, face="regular", track=0):
        if not track:  # measuring does not need a rendered surface
            return self.font(face, size).size(s)[0] / self.S
        return self.tsurf(s, face, size, DARK, track).get_width() / self.S

    def text(self, s, x, y, size=16, color=DARK, a=255, face="regular", align=0, track=0):
        """align 0=left 1=center 2=right. Returns the drawn width in virtual px."""
        if not s or a <= 0:
            return 0
        surf = self.tsurf(s, face, size, color, track)
        w = surf.get_width() / self.S
        if align == 1:
            x -= w / 2
        elif align == 2:
            x -= w
        px, py = int(x * self.S), int(y * self.S)
        if a >= 255:
            self.canvas.blit(surf, (px, py))
        else:
            tmp = surf.copy()
            tmp.set_alpha(int(a))
            self.canvas.blit(tmp, (px, py))
        return w

    def fit(self, s, size, maxw, face="regular"):
        key = (s, size, int(maxw), face)
        r = self._fit.get(key)
        if r is None:
            if len(self._fit) > 4000:
                self._fit.clear()
            r = s
            while len(r) > 1 and self.text_w(r, size, face) > maxw:
                r = r[:-1]
            self._fit[key] = r
        return r

    def cap_info(self, face, size):
        """(top, height) in device px of a capital letter inside a rendered line of this font."""
        key = (face, size)
        v = self._cap.get(key)
        if v is None:
            probe = self.font(face, size).render("H", True, (0, 0, 0))
            if not (probe.get_flags() & pygame.SRCALPHA):
                try:
                    probe = probe.convert_alpha()
                except pygame.error:
                    pass
            r = probe.get_bounding_rect()
            v = self._cap[key] = (r.top, max(1, r.height))
        return v

    def row_text(self, s, x, y, a=255, face="regular", color=DARK, align=0, size=None, center=ROW_CENTER):
        """Text for a list row whose selector bar is drawn at `y`: capitals are centred at y+center
        (this is what makes the text sit exactly inside the highlight bar like the original)."""
        size = size or ROW_SIZE
        top, h = self.cap_info(face, size)
        return self.text(s, x, y + center - (top + h / 2) / self.S, size, color, a, face, align)

    def ink_center_text(self, s, x, cy, size, color, a, face="regular", align=1, track=0):
        """Draw text so the middle of its visible ink is at cy (used for the pill label)."""
        surf = self.tsurf(s, face, size, color, track)
        r = surf.get_bounding_rect()
        return self.text(s, x, cy - (r.top + r.height / 2) / self.S, size, color, a, face, align, track)

    def fill_rect(self, x, y, w, h, color, a=255, target=None):
        S = self.S
        r = pygame.Rect(int(x * S), int(y * S), int(w * S), int(h * S))
        dst = target or self.canvas
        if a >= 255:
            dst.fill(color, r)
        else:
            key = (r.w, r.h, tuple(color), int(a))
            sf = self._rect_cache.get(key)
            if sf is None:
                if len(self._rect_cache) > 40:
                    self._rect_cache.clear()
                sf = pygame.Surface(r.size)
                sf.fill(color)
                sf.set_alpha(int(a))
                self._rect_cache[key] = sf
            dst.blit(sf, r.topleft)

    def dim(self, v, right=VW):
        v = int(v)
        if v < 255:
            self.canvas.fill((v, v, v), pygame.Rect(0, 0, int(right * self.S), self.ch),
                             special_flags=pygame.BLEND_RGB_MULT)

    # --------------------------------------------------------- shared widgets
    def header(self, icon, xoff, title, sub, a=255, bg_a=255, mode=0, line_to=800):
        """DrawHeader / DrawHeader_Ani. `line_to` lets the animation grow the line."""
        self.draw_bg(xoff, bg_a)
        x0 = xoff + MENU_ICON_OFF
        if line_to > x0:
            self.draw_strip("header_line", x0, 40, line_to - x0, 37, a)
            self.draw("header_dot", line_to - 4, 40, 8, 37, a)
        if mode:
            self.draw_cx(icon, xoff + MENU_ICON_OFF - 12, 40, 32, 32, a)
            tsize, ty = 20, 35
        else:
            self.draw_cx(icon, xoff + MENU_ICON_OFF - 20, 32, 48, 48, a)
            tsize, ty = 24, 31
        tw = self.text(title, x0 + 10, ty, tsize, DARK, a)
        if sub:
            width = 800 - (x0 + MENU_TITLE_OFF + tw) - 30
            sub = self.fit(sub, 20, width)
            self.text(sub, 800, 35, 20, DARK, a, align=2)

    def scrollbar(self, sel, count, y_inc, xoff, a):
        game_y = 120
        per_page = (512 - game_y * 2) // y_inc
        y_total = 512 - game_y * 2
        if count < per_page or count == 0:
            return
        if self.idle_time > 80:
            a = max(0, a - (self.idle_time - 80) * 4)
        self.draw_cx("scroll_bg", xoff, game_y, 6, y_total, a)
        self.draw_cx("scroll_lock", xoff, int(y_total * sel / count) + game_y, 4, per_page * 2, a)

    @staticmethod
    def list_alpha(cur, sel, per_page):
        mult = int(255.0 / per_page * 7 / 4)
        return clamp(255 - abs(sel - cur) * mult, 0, 255)

    def selector(self, x, y, a):
        self.draw_strip("mark_line", x, y, VW - x, 22, a)

    def footer(self, menu, a=255):
        items = PAD_HELP.get(menu, [])
        if not items or a <= 0:
            return
        size, ico = 16, 18
        parts, total = [], 0
        for btn, label in items:
            w = self.text_w(label, size, "regular", 1)
            parts.append((btn, label, w))
            total += ico + 4 + w + 22
        x = VW / 2 - (total - 22) / 2
        for btn, label, w in parts:
            self.draw("footer_ico_" + btn, x, 478, ico, ico, int(a * 0.55))
            self.text(label, x + ico + 4, 477, size, DARK, int(a * 0.55), track=1)
            x += ico + 4 + w + 22

    def footer_alpha(self):
        a = 255
        if self.idle_time > 80:
            a = max(0, 255 - (self.idle_time - 80) * 4)
        return a

    # ------------------------------------------------------------ list helpers
    def visible_games(self, menu):
        games = self.lists[menu]
        f = self.filters[menu].lower()
        if not f:
            return games
        key = (id(games), len(games), f)
        c = self._vis.get(menu)
        if c and c[0] == key:
            return c[1]
        res = [g for g in games if f in g.name.lower() or any(f in t.lower() for t in g.title_ids)]
        self._vis[menu] = (key, res)
        return res

    def draw_game_list(self, sel, games, a):
        game_y0, y_inc = 80, 20
        per_page = (512 - game_y0 * 2) // y_inc
        if not games:
            self.text("No games found", VW / 2, 240, 18, DARK, a, "light", align=1, track=1)
            return
        for x in range(sel - per_page // 2, min(len(games), sel + per_page // 2 + 2)):
            y = game_y0 + (x - (sel - per_page // 2)) * y_inc
            if x >= 0:
                g = games[x]
                al = a * self.list_alpha(x, sel, per_page) // 255
                if self.game_active(g):
                    self.draw_c("mark_arrow", MENU_ICON_OFF + MENU_TITLE_OFF / 2, y + ROW_CENTER, 7, 9, al)
                name = self.fit(g.name, ROW_SIZE, 800 - MENU_ICON_OFF * 3 - (MENU_ICON_OFF + MENU_TITLE_OFF) - 10)
                self.row_text(name, MENU_ICON_OFF + MENU_TITLE_OFF, y, al)
                self.row_text(g.title_id, 800 - MENU_ICON_OFF * 3, y, al)
                self.row_text(g.version, 800 - MENU_ICON_OFF, y, al)
            if x == sel:
                self.selector(0, y, a)
                self.draw_cx("mark_arrow", MENU_ICON_OFF - 20, y + ARROW_Y, ARROW_W, ARROW_H, a)
        self.scrollbar(sel, len(games), y_inc, 800, a)

    def draw_cheat_list(self, sel, game, a):
        game_y0, y_inc = 80, 20
        per_page = (512 - game_y0 * 2) // y_inc
        codes = game.codes or []
        for x in range(sel - per_page // 2, min(len(codes), sel + per_page // 2 + 2)):
            y = game_y0 + (x - (sel - per_page // 2)) * y_inc
            if x >= 0:
                c = codes[x]
                al = a * self.list_alpha(x, sel, per_page) // 255
                dx = self.row_text(c.name, MENU_ICON_OFF + MENU_TITLE_OFF * 3, y, al)
                dx += MENU_ICON_OFF + MENU_TITLE_OFF * 3
                if c.activated:
                    self.draw("cheat", MENU_ICON_OFF, y + PILL_Y, MENU_TITLE_OFF * 3 - 15, PILL_H, al)
                    self.ink_center_text("constant" if c.cwrite else "once",
                                         MENU_ICON_OFF + (MENU_TITLE_OFF * 3 - 15) / 2, y + PILL_CENTER,
                                         12, CREAM, al)
                    names = [o.names[o.sel] for o in c.options if o.names]
                    if names:
                        self.row_text(" (" + ", ".join(names) + ")", dx, y, al, "bold")
            if x == sel:
                self.selector(0, y, a)
                self.draw_cx("mark_arrow", MENU_ICON_OFF - 20, y + ARROW_Y, ARROW_W, ARROW_H, a)
        self.scrollbar(sel, len(codes), y_inc, 800, a)

    def draw_cheats_menu(self, sel, a=255, hdr_a=255, line_to=800):
        self.header("header_ico_cht", 0, "Cheats", self.game.name if self.game else "", hdr_a, 255, 0, line_to)
        if self.game:
            self.draw_cheat_list(sel, self.game, a)

    def draw_lines_panel(self, lines, x_off, sel, a, y_inc=20, option_mode=False):
        """DrawCodes / DrawOptions: lines of a side panel."""
        y0 = 80
        per_page = (512 - y0 * 2) // y_inc
        start = sel - per_page // 2
        for c in range(start, start + per_page):
            y = y0 + (c - start) * y_inc
            if 0 <= c < len(lines):
                al = a * self.list_alpha(c, sel, per_page) // 255
                self.row_text(lines[c], x_off + MENU_ICON_OFF, y, al)
                if c == sel:
                    self.draw_strip("mark_line", x_off, y, VW - x_off, 22, a)
        self.scrollbar(sel, len(lines), y_inc, 800, a)

    def panel_lines(self, kind):
        code = self.game.codes[self.old_sel[M_CHEATS]] if self.game and self.game.codes else None
        if code is None:
            return []
        if kind == M_VIEW:
            return code.resolved_lines() or ["(no code lines)"]
        if self.option_index < len(code.options):
            return list(code.options[self.option_index].names)
        return []

    def draw_panel(self, kind, left, a, rgb, content_a=None):
        self.draw_cheats_menu(self.old_sel[M_CHEATS])
        self.dim(rgb, left)
        sw = self.raw["edit_shadow"].get_width()
        self.draw("edit_shadow", left - sw + 1, 0, sw, VH, a)
        title = "Cheat View" if kind == M_VIEW else "Cheat Option"
        code = self.game.codes[self.old_sel[M_CHEATS]] if self.game and self.game.codes else None
        self.header("header_ico_opt", left, title, code.name if code else "", a, 255, 1, 800)
        ca = a if content_a is None else content_a
        sel = self.sel if self.menu_id == kind else 0
        self.draw_lines_panel(self.panel_lines(kind), left, sel, ca)

    def draw_main(self, sel, icon_a=None, logo_a=255, bg_a=255, desc=True, show_icons=True, labels=True):
        self.draw_bg(0, bg_a)
        w, h = 500, 88
        self.draw("titlescr_logo", 424 - w / 2, 256 - h / 2 - 100, w, h, logo_a)
        self.text("PlayStation 3 Hacking System", VW / 2, 210, 18, DARK, logo_a, "light", align=1, track=2)
        if not desc:
            return
        self.text("www.gamehacking.org/artemis", VW / 2, 480, 12, DARK, logo_a, "light", align=1, track=2)
        if not show_icons:
            return
        names = ["xmb", "cht", "net", "opt", "abt"]
        labs = ["Start game", "Cheats", "Online DB", "Options", "About"]
        xs = [200, 300, 400, 505, 600]
        for i, (n, lab, x) in enumerate(zip(names, labs, xs)):
            al = 255 if (sel == i) else 32
            if icon_a is not None:
                al = min(al, icon_a) if sel == i else icon_a
            self.draw("titlescr_ico_" + n, x, 320, MENU_MAIN_ICON_WIDTH, 64, al)
            if labels:
                self.text(lab, x + MENU_MAIN_ICON_WIDTH / 2, 390, 12, DARK, al, align=1, track=1)

    def main_icon_at(self, vpos):
        for i, x in enumerate([200, 300, 400, 505, 600]):
            if x <= vpos[0] <= x + MENU_MAIN_ICON_WIDTH and 320 <= vpos[1] <= 410:
                return i
        return -1

    def draw_about(self, a=255, hdr_a=255, line_to=800):
        self.header("header_ico_abt", 0, "About", VERSION, hdr_a, 255, 0, line_to)
        if a <= 0:
            return
        cx = VW / 2
        self.text("Thank You for using Artemis!", cx, 70, 20, DARK, a, "bold", align=1)
        self.text("an open source hacking system", cx, 100, 12, DARK, a, align=1)
        self.text("PlayStation 3 version:", cx, 140, 18, DARK, a, "bold", align=1)
        rows = [("Berion", "Designer"), ("NzV", "PS3MAPI"), ("Dnawrkshp", "Programmer"), ("Bucanero", "Network code")]
        y = 170
        for l, r in rows:
            self.text(l, cx - 10, y, 14, DARK, a, align=2)
            self.text(r, cx + 10, y, 14, DARK, a, "light")
            y += 24
        self.text("Project Artemis:", cx, 302, 18, DARK, a, "bold", align=1)
        y = 331
        for l, r in [("Lazy Bastard", "Project Founder"), ("PS2Dragon", "Artemis Logo")]:
            self.text(l, cx - 10, y, 14, DARK, a, align=2)
            self.text(r, cx + 10, y, 14, DARK, a, "light")
            y += 24
        self.text("PC version (Python):", cx, 394, 18, DARK, a, "bold", align=1)
        self.text("MexrlDev", cx - 10, 424, 14, DARK, a, align=2)
        self.text("Python port", cx + 10, 424, 14, DARK, a, "light")
        self.text("This is a PC copy of a PS3 Artemis made with Python.  Press F1 for controls.",
                  cx, 448, 11, DARK, int(a * 0.7), "light", align=1)

    def draw_options(self, sel, a=255, hdr_a=255, line_to=800):
        self.header("header_ico_opt", 0, "Options", None, hdr_a, 255, 0, line_to)
        if a <= 0:
            return
        y = 100
        for i, (name, kind, key) in enumerate(OPTION_ROWS):
            if i == sel:
                self.draw_strip("mark_line", 0, y, VW, 22, a)
            self.row_text(name, MENU_ICON_OFF + MENU_TITLE_OFF, y, a)
            if kind == "bool":
                self.draw("opt_on" if self.opt[key] else "opt_off", 671, y - 3.5, 20, 28, a)
            elif kind == "call":
                self.draw("footer_ico_cross", 671, y + 2, 18, 18, a)
            elif kind == "list":
                self.row_text("<  %s  >" % EXPORT_FORMATS[self.opt[key]], 700, y, a, align=1)
            elif kind == "inc":
                self.row_text("- %d +" % self.opt[key], 682, y, a, align=1)
            y += 30

    # --------------------------------------------------------------- frame IO
    def pump(self):
        """Process events. Returns a list of actions such as 'up', 'cross', ('click', pos)."""
        acts = []
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
                acts.append("quit")
            elif e.type == pygame.KEYDOWN:
                k = e.key
                repeat = bool(getattr(e, "repeat", 0))
                text_mod = pygame.key.get_mods() & (pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META)
                m = {pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
                     pygame.K_RETURN: "cross", pygame.K_KP_ENTER: "cross",
                     pygame.K_ESCAPE: "circle", pygame.K_BACKSPACE: "circle",
                     pygame.K_SPACE: "square", pygame.K_t: "triangle",
                     pygame.K_PAGEUP: "l1", pygame.K_PAGEDOWN: "r1",
                     pygame.K_HOME: "home", pygame.K_END: "end", pygame.K_F1: "help"}
                if not repeat and (k == pygame.K_F11 or (k == pygame.K_f and not self.typing)):
                    self.toggle_fullscreen()
                elif k in m:
                    action = m[k]
                    if not repeat or action in ("up", "down", "left", "right", "l1", "r1", "home", "end"):
                        acts.append(action)
                    if e.unicode and not text_mod:
                        acts.append(("key", e.unicode))
                else:
                    if e.unicode and not text_mod:
                        acts.append(("key", e.unicode))
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    acts.append(("click", self.to_virtual(e.pos)))
                elif e.button == 3:
                    acts.append("circle")
            elif e.type == pygame.MOUSEWHEEL:
                acts.append("up" if e.y > 0 else "down")
            elif e.type == pygame.MOUSEMOTION:
                self.mouse_pos = self.to_virtual(e.pos)
                acts.append(("motion", self.mouse_pos))
        real = [a for a in acts if not (isinstance(a, tuple) and a[0] in ("key", "motion"))]
        self.idle_time = 0 if real else self.idle_time + 1
        return acts

    def tick(self):
        """Present one frame. With vsync the monitor sets the pace (any refresh rate); without it we cap at 60."""
        ft = self.present()
        self.frame_n += 1
        if self.vsync_on is None:
            self.flip_times.append(ft)
            if len(self.flip_times) >= 24:
                self.vsync_on = max(self.flip_times[4:]) > 0.003
        if self.vsync_on:
            self.clock.tick()
        else:
            self.clock.tick(FPS)

    def anim(self, frames, fn):
        """Blocking, TIME-based animation loop. fn(pos) draws the frame at position `pos` (in 1/60 s ticks,
        fractional) and returns True to stop early. A slow frame skips ahead instead of slowing the animation,
        and one long hitch can advance at most 2.5 ticks so it never looks like a jump."""
        gc.disable()
        try:
            pos, prev, first = 0.0, _clock(), True
            while self.running:
                acts = self.pump()
                if not self.running:
                    return
                if any(a in ("cross", "circle") or (isinstance(a, tuple) and a[0] == "click") for a in acts):
                    break
                now = _clock()
                if not first:
                    pos += clamp((now - prev) * FPS, 0.0, 2.5)
                first, prev = False, now
                if pos >= frames:
                    break
                if fn(pos):
                    break
                self.tick()
        finally:
            gc.enable()

    # ------------------------------------------------------------ animations
    def main_ani(self):
        def phase1(ani):
            bg_a = max(0x20, ani * 2)
            logo_a = 0 if ani < 0x30 else min(255, (ani - 0x20) * 3)
            self.draw_main(self.sel, bg_a=bg_a, logo_a=logo_a, desc=False)
        self.fill_black()
        self.anim(MENU_ANI_MAX, phase1)

        def phase2(ani):
            icon_a = min(32, ani * 4)
            self.draw_main(self.sel, icon_a=icon_a, labels=False)
            return icon_a >= 32
        self.anim(MENU_ANI_MAX // 2, phase2)

    def fill_black(self):
        self.canvas.fill((0, 0, 0))

    def menu_ani(self, icon, title, sub, body):
        def f(ani):
            icon_a = min(255, ani * 2)
            line_to = min(800, MENU_ICON_OFF + ani * 12)
            self.draw_bg(0, 255)
            body_a = clamp((icon_a - MENU_ANI_MAX // 2) * 2, 0, 255)
            body(body_a, icon_a, line_to)
            return body_a >= 255
        self.anim(MENU_ANI_MAX, f)

    def panel_in(self, kind):
        def f(ani):
            icon_a = min(255, ani * 4 + 0x40)
            left = max(MENU_SPLIT_OFF, 848 - ani * 36)
            rgb = max(0xD0, 0xFF - (848 - left) // 12)
            self.draw_panel(kind, left, icon_a, rgb, 0 if icon_a < 0x8F else icon_a)
            return 848 - ani * 36 < MENU_SPLIT_OFF // 2
        self.anim(MENU_ANI_MAX, f)

    def panel_out(self, kind):
        left = [MENU_SPLIT_OFF]

        def f(ani):
            left[0] = min(848, MENU_SPLIT_OFF + (ani + 1) * 36)
            a = int((848 - left[0]) / 848.0 * 255)
            rgb = max(0xD0, 0xFF - (848 - left[0]) // 12)
            self.draw_panel(kind, left[0], a, rgb, 0)
            return left[0] >= 848
        self.anim(MENU_ANI_MAX, f)

    # ------------------------------------------------------------ modal bits
    def dialog(self, msg, yesno=False, error=False):
        self.draw_current()
        lines = msg.split("\n")
        col = RED if error else DARK
        # draw the whole dialog once into `base`; the loop below only blits it
        self.fill_rect(0, 0, VW, VH, (0, 0, 0), 150)
        bh = 120 + 20 * len(lines)
        y0 = VH / 2 - bh / 2
        self.fill_rect(184, y0, 480, bh, CREAM)
        self.fill_rect(184, y0, 480, 3, DARK)
        self.fill_rect(184, y0 + bh - 3, 480, 3, DARK)
        self.draw_c("circle_error_dark" if error else "circle_loading_bg", 424, y0 + 38, 40, 40)
        for i, ln in enumerate(lines):
            self.text(ln, 424, y0 + 70 + 20 * i, 16, col, 255, align=1, track=1)
        by = y0 + bh - 32
        if yesno:
            self.draw("footer_ico_cross", 340, by, 18, 18)
            self.text("Yes", 364, by, 16, DARK, 255, track=1)
            self.draw("footer_ico_circle", 440, by, 18, 18)
            self.text("No", 464, by, 16, DARK, 255, track=1)
        else:
            self.draw("footer_ico_cross", 395, by, 18, 18)
            self.text("OK", 419, by, 16, DARK, 255, track=1)
        base = self.canvas.copy()
        result = None
        while self.running and result is None:
            for a in self.pump():
                if a == "cross":
                    result = True
                elif a == "circle":
                    result = False if yesno else True
                elif isinstance(a, tuple) and a[0] == "click":
                    result = True
            self.canvas.blit(base, (0, 0))
            self.tick()
        return bool(result)

    def prompt(self, title, initial=""):
        self.draw_current()
        self.fill_rect(0, 0, VW, VH, (0, 0, 0), 150)
        self.fill_rect(164, 200, 520, 112, CREAM)
        self.fill_rect(164, 200, 520, 3, DARK)
        self.text(title, 424, 214, 16, DARK, 255, "bold", align=1)
        self.fill_rect(184, 248, 480, 28, (255, 255, 255))
        self.text("Enter = OK    Esc = Cancel", 424, 284, 12, DARK, 160, "light", align=1, track=1)
        base = self.canvas.copy()
        buf, done, ok = initial, False, False
        self.typing = True
        try:
            while self.running and not done:
                acts = self.pump()
                bs = any(isinstance(a, tuple) and a[0] == "key" and a[1] == "\x08" for a in acts)
                for a in acts:
                    if a == "cross":
                        done = ok = True
                    elif a == "circle" and not bs:
                        done = True
                    elif isinstance(a, tuple) and a[0] == "key" and a[1]:
                        ch = a[1]
                        if ch == "\x08":
                            buf = buf[:-1]
                        elif len(ch) == 1 and 32 <= ord(ch) < 127:
                            buf += ch
                self.canvas.blit(base, (0, 0))
                cursor = "|" if int(time.time() * 2) % 2 == 0 else ""
                self.text(self.fit(buf + cursor, 16, 460), 192, 252, 16, DARK)
                self.tick()
        finally:
            self.typing = False
        return buf if ok else None

    def loading(self, message, worker):
        """Spinner screen while worker() runs in a thread. Returns (result, error)."""
        out = {"r": None, "e": None, "done": False}
        self.progress = 0.0

        def run():
            try:
                out["r"] = worker()
            except Exception as ex:  # noqa: BLE001
                out["e"] = ex
            out["done"] = True

        # static layer (background, text, spinner ring) is drawn once; only the spinner arc is redrawn
        self.canvas.fill((0, 0, 0))
        self.draw_bg(0, 255)
        self.draw_c("circle_loading_bg", 424, 256, 89, 89)
        self.text(message, 424, 336, 14, DARK, 255, align=1, track=2)
        base = self.canvas.copy()
        seek = self.tex("circle_loading_seek", 89, 89)
        S = self.S
        old_switch = sys.getswitchinterval()
        sys.setswitchinterval(0.0005)          # let the draw loop win the GIL back quickly from the worker
        threading.Thread(target=run, daemon=True).start()
        angle, prev, last_pct = 0.0, _clock(), -1
        try:
            while not out["done"] and self.running:
                self.pump()
                now = _clock()
                angle += clamp(now - prev, 0.0, 0.1) * 6.0   # 0.1 rad per 1/60 s like the PS3 build
                prev = now
                self.canvas.blit(base, (0, 0))
                rot = pygame.transform.rotozoom(seek, -math.degrees(angle), 1.0)
                self.canvas.blit(rot, rot.get_rect(center=(int(424 * S), int(256 * S))))
                if self.progress > 0:
                    self.text("%d%%" % int(self.progress * 100), 424, 362, 18, DARK, 255, align=1)
                self.tick()
        finally:
            sys.setswitchinterval(old_switch)
        return out["r"], out["e"]

    def closing_animation(self):
        steps = 4 * FPS

        def f(i):
            self.canvas.fill((255, 255, 255))
            self.draw_c("titlescr_logo", VW / 2, VH / 2, 340, 60)
            bar = int(i / steps * (VH / 2))
            self.fill_rect(0, 0, VW, bar, (0, 0, 0))
            self.fill_rect(0, VH - bar, VW, bar, (0, 0, 0))
        self.anim(steps, f)
        self.running = False

    def help_screen(self):
        """Controller diagram (help.png) plus the keyboard bindings."""
        done = False
        while self.running and not done:
            for a in self.pump():
                if a in ("cross", "circle", "help") or (isinstance(a, tuple) and a[0] == "click"):
                    done = True
            self.draw_bg(0, 255)
            ih = 400
            iw = ih * self.raw["help"].get_width() / self.raw["help"].get_height()
            self.draw("help", VW - iw - 24, 56, iw, ih)
            self.text("Controls", 40, 56, 26, DARK, 255, "bold")
            y = 112
            for k, v in CONTROLS:
                self.text(k, 40, y, 13, DARK, 255, "bold")
                self.text(v, 40, y + 18, 13, DARK, 200, "light")
                y += 42
            self.text("This is a PC copy of a PS3 Artemis made with Python.  (Made by MexrlDev)",
                      VW / 2, 470, 12, DARK, 200, "light", align=1)
            self.tick()

    # ------------------------------------------------------------ data loading
    def reload_user(self):
        os.makedirs(USER_DIR, exist_ok=True)
        self.lists[M_USER] = ncl.scan_games(USER_DIR, self.opt["sort"])

    def reload_online(self):
        os.makedirs(ONLINE_DIR, exist_ok=True)
        self.lists[M_ONLINE] = ncl.scan_games(ONLINE_DIR, self.opt["sort"])

    def _count_ncl(self, folder):
        """Recursive count of .ncl files under folder."""
        if not os.path.isdir(folder):
            return 0
        total = 0
        for _, _, filenames in os.walk(folder):
            total += sum(1 for f in filenames if f.lower().endswith(".ncl"))
        return total

    def _flatten_ncl(self, root):
        """Move all .ncl files under root/subfolders into root. Safe on collisions."""
        moved = 0
        if not os.path.isdir(root):
            return 0
        root_abs = os.path.abspath(root)
        to_move = []
        for dirpath, _, filenames in os.walk(root):
            if os.path.abspath(dirpath) == root_abs:
                continue
            for fn in filenames:
                if fn.lower().endswith(".ncl"):
                    to_move.append(os.path.join(dirpath, fn))
        for src in to_move:
            fn = os.path.basename(src)
            dst = os.path.join(root, fn)
            if os.path.abspath(src) == os.path.abspath(dst):
                continue
            if os.path.exists(dst):
                base, ext = os.path.splitext(fn)
                i = 1
                while os.path.exists(os.path.join(root, f"{base}_{i}{ext}")):
                    i += 1
                dst = os.path.join(root, f"{base}_{i}{ext}")
            try:
                shutil.move(src, dst)
                moved += 1
            except OSError:
                pass
        return moved

    def unpack_db(self, zpath, lo=0.0):
        """Extract .ncl files into ONLINE_DIR via a temp staging dir.
        Flattens subfolders, verifies at least one .ncl exists, atomic-swaps in.
        Raises RuntimeError if the archive yields no .ncl files."""
        target = ONLINE_DIR
        os.makedirs(target, exist_ok=True)
        tmp_dir = target + "_unpack_tmp"
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
                if not names:
                    raise RuntimeError("Zip archive is empty")
                n = len(names)
                for i in range(0, n, 40):
                    z.extractall(tmp_dir, names[i:i + 40])
                    self.progress = lo + (1.0 - lo) * min(1.0, (i + 40) / n)
                    time.sleep(0.002)
            self._flatten_ncl(tmp_dir)
            count = self._count_ncl(tmp_dir)
            if count == 0:
                sample = []
                for dirpath, _, filenames in os.walk(tmp_dir):
                    for fn in filenames:
                        sample.append(os.path.relpath(os.path.join(dirpath, fn), tmp_dir))
                        if len(sample) >= 6:
                            break
                    if len(sample) >= 6:
                        break
                raise RuntimeError(
                    f"Zip has {n} entries but none are .ncl files. "
                    f"Sample entries: {sample}")
            for fn in os.listdir(tmp_dir):
                src = os.path.join(tmp_dir, fn)
                dst = os.path.join(target, fn)
                if os.path.exists(dst):
                    try:
                        if os.path.isfile(dst) or os.path.islink(dst):
                            os.remove(dst)
                        elif os.path.isdir(dst):
                            shutil.rmtree(dst)
                    except OSError:
                        pass
                try:
                    shutil.move(src, dst)
                except OSError:
                    pass
            return count
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def first_run_unpack(self):
        if self._count_ncl(ONLINE_DIR) > 0:
            return
        bundled = os.path.join(DATA, "cheatdb.zip")
        if not os.path.exists(bundled):
            return
        _, err = self.loading("Unpacking cheat database", lambda: self.unpack_db(bundled))
        if err:
            self.dialog("Could not unpack the cheat database:\n%s" % str(err)[:140], error=True)

    def download_db(self):
        tmp = os.path.join(BASE, "cheatdb_download.zip")
        try:
            req = urllib.request.Request(DB_URL, headers={"User-Agent": "ArtemisPC"})
            with urllib.request.urlopen(req, timeout=25) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress = got / total * 0.5
            size = os.path.getsize(tmp)
            if size < 1024:
                raise RuntimeError(
                    f"Download too small ({size} bytes) - server likely returned an error page")
            try:
                with zipfile.ZipFile(tmp) as z:
                    if not z.namelist():
                        raise RuntimeError("Downloaded zip is empty")
            except zipfile.BadZipFile:
                raise RuntimeError(f"Downloaded file is not a valid zip ({size} bytes)")
            self.unpack_db(tmp, lo=0.5)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # -------------------------------------------------------------- navigation
    def set_menu(self, new):
        old = self.menu_id
        ani = self.opt["ani"]
        if old == M_VIEW and ani:
            self.panel_out(M_VIEW)
        elif old == M_OPTPANEL and ani:
            self.panel_out(M_OPTPANEL)

        if new == M_MAIN:
            if ani or old == M_MAIN:
                self.main_ani()
        elif new in (M_USER, M_ONLINE):
            if ani:
                games = self.visible_games(new)
                sub = "User List" if new == M_USER else "Online DB"
                sel0 = self.old_sel[new]
                self.menu_ani("header_ico_cht", "Cheats", sub, lambda a, ia, lt: (
                    self.header("header_ico_cht", 0, "Cheats", sub, ia, 255, 0, lt),
                    self.draw_game_list(sel0, games, a)))
        elif new == M_ABOUT:
            if ani:
                self.menu_ani("header_ico_abt", "About", VERSION,
                              lambda a, ia, lt: self.draw_about(clamp((a - 0), 0, 255), ia, lt))
        elif new == M_OPTIONS:
            if ani:
                self.menu_ani("header_ico_opt", "Options", None,
                              lambda a, ia, lt: self.draw_options(self.old_sel[M_OPTIONS], a, ia, lt))
        elif new == M_CHEATS:
            if old in (M_USER, M_ONLINE):
                self.old_sel[M_CHEATS] = 0
            if ani and old not in (M_VIEW, M_OPTPANEL):
                sel0 = self.old_sel[M_CHEATS]
                self.menu_ani("header_ico_cht", "Cheats", self.game.name,
                              lambda a, ia, lt: self.draw_cheats_menu(sel0, a, ia, lt))
        elif new == M_VIEW:
            self.old_sel[M_VIEW] = 0
            if ani:
                self.panel_in(M_VIEW)
        elif new == M_OPTPANEL:
            self.old_sel[M_OPTPANEL] = 0
            if ani:
                self.panel_in(M_OPTPANEL)

        self.old_sel[old] = self.sel
        if self.last_menu[old] != new:
            self.last_menu[new] = old
        self.menu_id = new
        self.sel = self.old_sel[new]
        self.idle_time = 0

    def back(self):
        self.set_menu(self.last_menu[self.menu_id])

    def move(self, count, step):
        if count > 0:
            self.sel = clamp(self.sel + step, 0, count - 1)

    def letter_jump(self, games, direction):
        if not games:
            return
        cur = games[self.sel].name[:1].upper()
        i = self.sel
        while 0 <= i + direction < len(games):
            i += direction
            first = games[i].name[:1].upper()
            if first != cur:
                if direction < 0:  # land on the first game of that letter
                    while i > 0 and games[i - 1].name[:1].upper() == first:
                        i -= 1
                self.sel = i
                return
        self.sel = 0 if direction < 0 else len(games) - 1

    # ---------------------------------------------------------------- actions
    def export_cheats(self):
        sections, ngames, ncodes = [], 0, 0
        for key, info in self.state["act"].items():
            path = os.path.join(BASE, key)
            if not os.path.exists(path) or not info:
                continue
            name, ids, ver = ncl.parse_filename(os.path.basename(path))
            codes = ncl.read_ncl(path)
            lines = ["# %s %s %s" % (name, " ".join(ids), ver)]
            n = 0
            for idx, ci in info.items():
                i = int(idx)
                if i >= len(codes):
                    continue
                c = codes[i]
                for o, s in zip(c.options, ci.get("sel", [])):
                    o.sel = clamp(int(s), 0, max(0, len(o.names) - 1))
                if self.opt["export"] == 0:
                    lines.append("%s | %s" % (c.name, "constant" if ci.get("cw") else "once"))
                    lines += ["  " + l for l in c.resolved_lines()]
                else:
                    lines += [c.name, "1" if ci.get("cw") else "0", c.author or "Artemis PC"]
                    lines += c.resolved_lines() + ["#"]
                n += 1
            if n:
                sections.append("\n".join(lines))
                ngames += 1
                ncodes += n
        if ncodes == 0:
            return 0, 0
        with open(EXPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n\n".join(sections) + "\n")
        return ngames, ncodes

    def do_start_game(self):
        g, c = self.export_cheats()
        if c == 0:
            self.dialog("No cheats are enabled yet.\nOpen Cheats and press Enter on a code.")
            return
        self.dialog("%d cheat(s) from %d game(s) written to\n%s" % (c, g, os.path.basename(EXPORT_FILE)))
        if self.dialog("Exit Artemis?", yesno=True):
            self.closing_animation()

    def do_update(self):
        self.progress = 0.0
        _, err = self.loading("Downloading latest cheats", self.download_db)
        if err:
            self.dialog("Update failed:\n%s" % str(err)[:200], error=True)
            return
        self.reload_online()
        n = len(self.lists[M_ONLINE])
        if n == 0:
            self.dialog("Update finished but no games were found.\n"
                        "The cheat database format may have changed.", error=True)
            return
        self.dialog("Local cheat database updated.\n%d games available." % n)

    def do_clear(self):
        if not self.dialog("Delete the local cheat cache?", yesno=True):
            return
        shutil.rmtree(ONLINE_DIR, ignore_errors=True)
        os.makedirs(ONLINE_DIR, exist_ok=True)
        self.lists[M_ONLINE] = []
        self.dialog("Local cache cleared.\nUse Update Local Cheats to download it again.")

    def open_game(self, menu, games):
        if not games:
            return
        self.game = games[self.sel]
        self.game_from = menu
        self.load_codes(self.game)
        self.set_menu(M_CHEATS)

    def toggle_code(self, idx):
        code = self.game.codes[idx]
        if code.activated:
            code.activated = False
            self.persist_game(self.game)
            return
        if code.options:
            self.code_for_option = idx
            self.option_index = 0
            self.old_sel[M_CHEATS] = idx
            self.set_menu(M_OPTPANEL)
            self.sel = code.options[0].sel
            return
        code.activated = True
        self.persist_game(self.game)

    # ----------------------------------------------------------- input per menu
    def handle(self, acts):
        for a in acts:
            if isinstance(a, tuple) and a[0] == "motion":
                if self.menu_id == M_MAIN:
                    i = self.main_icon_at(a[1])
                    if i >= 0:
                        self.sel = i
                continue
            if a == "help":
                self.help_screen()
                continue
            if not isinstance(a, tuple) or a[0] == "click":
                getattr(self, "input_%d" % self.menu_id)(a)
                if not self.running:
                    return

    def click_row(self, vpos, y0, y_inc, first_visible, count):
        row = int((vpos[1] - y0) // y_inc) + first_visible
        return row if 0 <= row < count and y0 <= vpos[1] else -1

    def input_0(self, a):  # main
        if a == "left":
            self.sel = max(0, self.sel - 1)
        elif a == "right":
            self.sel = min(4, self.sel + 1)
        elif isinstance(a, tuple):
            i = self.main_icon_at(a[1])
            if i < 0:
                return
            self.sel = i
            a = "cross"
        if a == "cross":
            if self.sel == 0:
                self.do_start_game()
            elif self.sel == 1:
                self.set_menu(M_USER)
            elif self.sel == 2:
                self.set_menu(M_ONLINE)
            elif self.sel == 3:
                self.set_menu(M_OPTIONS)
            elif self.sel == 4:
                self.set_menu(M_ABOUT)
        elif a == "circle":
            if self.dialog("Exit to desktop?", yesno=True):
                self.closing_animation()

    def input_list(self, menu, a):
        games = self.visible_games(menu)
        n = len(games)
        if isinstance(a, tuple):  # click
            row = self.click_row(a[1], 80, 20, self.sel - 8, n)
            if row >= 0:
                if row == self.sel:
                    self.open_game(menu, games)
                else:
                    self.sel = row
            return
        if a == "up":
            self.move(n, -1)
        elif a == "down":
            self.move(n, 1)
        elif a == "left":
            self.move(n, -10)
        elif a == "right":
            self.move(n, 10)
        elif a == "home":
            self.sel = 0
        elif a == "end":
            self.sel = max(0, n - 1)
        elif a == "l1":
            self.letter_jump(games, -1)
        elif a == "r1":
            self.letter_jump(games, 1)
        elif a == "cross":
            self.open_game(menu, games)
        elif a == "circle":
            self.set_menu(M_MAIN)
        elif a == "triangle":
            txt = self.prompt("Filter by name or title ID", self.filters[menu])
            if txt is not None:
                self.filters[menu] = txt.strip()
                self.sel = 0
                self.old_sel[menu] = 0
        elif a == "square":
            self.reload_user() if menu == M_USER else self.reload_online()
            self.sel = clamp(self.sel, 0, max(0, len(self.visible_games(menu)) - 1))

    def input_1(self, a):
        self.input_list(M_USER, a)

    def input_2(self, a):
        self.input_list(M_ONLINE, a)

    def input_3(self, a):  # about
        if a in ("circle", "cross") or isinstance(a, tuple):
            self.set_menu(M_MAIN)

    def input_4(self, a):  # options
        n = len(OPTION_ROWS)
        name, kind, key = OPTION_ROWS[self.sel]
        if isinstance(a, tuple):
            row = self.click_row(a[1], 100, 30, 0, n)
            if row < 0:
                return
            self.sel = row
            name, kind, key = OPTION_ROWS[row]
            a = "cross"
        if a == "up":
            self.sel = max(0, self.sel - 1)
        elif a == "down":
            self.sel = min(n - 1, self.sel + 1)
        elif a == "circle":
            self.save_config()
            self.set_menu(M_MAIN)
        elif a in ("left", "right", "cross"):
            d = -1 if a == "left" else 1
            if kind == "bool" and a in ("cross", "left", "right"):
                self.opt[key] = not self.opt[key]
                self.after_option(key)
            elif kind == "inc" and a in ("left", "right"):
                self.opt[key] = clamp(self.opt[key] + d, 0, 60)
            elif kind == "inc" and a == "cross":
                self.opt[key] = clamp(self.opt[key] + 1, 0, 60)
            elif kind == "list":
                self.opt[key] = (self.opt[key] + d) % len(EXPORT_FORMATS)
            elif kind == "call" and a == "cross":
                self.do_update() if key == "update" else self.do_clear()
            self.save_config()

    def after_option(self, key):
        if key == "music":
            self.apply_music()
        elif key == "fullscreen":
            self.set_window(self.opt["fullscreen"])
        elif key == "sort":
            self.reload_user()
            self.reload_online()

    def input_5(self, a):  # cheat selection
        codes = self.game.codes or []
        n = len(codes)
        if isinstance(a, tuple):
            row = self.click_row(a[1], 80, 20, self.sel - 8, n)
            if row >= 0:
                if row == self.sel:
                    self.toggle_code(row)
                else:
                    self.sel = row
            return
        if a == "up":
            self.move(n, -1)
        elif a == "down":
            self.move(n, 1)
        elif a == "left":
            self.move(n, -10)
        elif a == "right":
            self.move(n, 10)
        elif a == "home":
            self.sel = 0
        elif a == "end":
            self.sel = max(0, n - 1)
        elif a == "circle":
            self.set_menu(self.game_from)
        elif n:
            code = codes[self.sel]
            if a == "cross":
                self.toggle_code(self.sel)
            elif a == "square":
                code.cwrite = not code.cwrite
                if code.activated:
                    self.persist_game(self.game)
            elif a == "triangle":
                self.old_sel[M_CHEATS] = self.sel
                self.set_menu(M_VIEW)

    def input_6(self, a):  # view code
        n = len(self.panel_lines(M_VIEW))
        if a == "up":
            self.move(n, -1)
        elif a == "down":
            self.move(n, 1)
        elif a == "left":
            self.move(n, -10)
        elif a == "right":
            self.move(n, 10)
        elif a in ("circle",) or isinstance(a, tuple):
            self.back_to_cheats()

    def back_to_cheats(self):
        self.set_menu(M_CHEATS)

    def input_7(self, a):  # option panel
        code = self.game.codes[self.code_for_option if self.code_for_option is not None else self.old_sel[M_CHEATS]]
        n = len(self.panel_lines(M_OPTPANEL))
        if a == "up":
            self.move(n, -1)
        elif a == "down":
            self.move(n, 1)
        elif a == "circle":
            self.code_for_option = None
            self.set_menu(M_CHEATS)
        elif a == "cross" and n:
            code.options[self.option_index].sel = self.sel
            self.option_index += 1
            if self.option_index >= len(code.options):
                code.activated = True
                self.persist_game(self.game)
                self.code_for_option = None
                self.set_menu(M_CHEATS)
            else:
                self.sel = code.options[self.option_index].sel
                self.old_sel[M_OPTPANEL] = self.sel
        elif isinstance(a, tuple):
            row = self.click_row(a[1], 80, 20, self.sel - 8, n)
            if row >= 0:
                self.sel = row

    # ------------------------------------------------------------- frame draw
    def draw_current(self):
        m = self.menu_id
        if m == M_MAIN:
            self.draw_main(self.sel, icon_a=None)
        elif m in (M_USER, M_ONLINE):
            games = self.visible_games(m)
            sub = "User List" if m == M_USER else "Online DB"
            if self.filters[m]:
                sub += "  [filter: %s]" % self.filters[m]
            self.header("header_ico_cht", 0, "Cheats", sub)
            self.draw_game_list(self.sel, games, 255)
        elif m == M_ABOUT:
            self.draw_about()
        elif m == M_OPTIONS:
            self.draw_options(self.sel)
        elif m == M_CHEATS:
            self.draw_cheats_menu(self.sel)
        elif m in (M_VIEW, M_OPTPANEL):
            self.draw_panel(m, MENU_SPLIT_OFF, 255, 0xD0)
        self.footer(m, self.footer_alpha())

    # ------------------------------------------------------------------- main
    def warm(self):
        """Pre-scale every image and pre-render common text once, so nothing is built mid-animation."""
        for n in ("xmb", "cht", "net", "opt", "abt"):
            self.tex("titlescr_ico_" + n, MENU_MAIN_ICON_WIDTH, 64)
        self.tex("titlescr_logo", 500, 88)
        for n in ("header_ico_cht", "header_ico_abt", "header_ico_opt"):
            self.tex(n, 48, 48)
        self.tex("header_ico_opt", 32, 32)
        self.tex("header_dot", 8, 37)
        for nm in ("header_line", "mark_line"):
            self.draw_strip(nm, 0, 0, 1, 37 if nm == "header_line" else 22, 1)
        self.tex("scroll_bg", 6, 272)
        self.tex("scroll_lock", 4, 26)
        self.tex("mark_arrow", ARROW_W, ARROW_H)
        self.tex("mark_arrow", 7, 9)
        self.tex("cheat", MENU_TITLE_OFF * 3 - 15, PILL_H)
        self.tex("opt_on", 20, 28)
        self.tex("opt_off", 20, 28)
        self.tex("edit_shadow", self.raw["edit_shadow"].get_width(), VH)
        for n in ("cross", "circle", "square", "triangle"):
            self.tex("footer_ico_" + n, 18, 18)
        self.tex("circle_loading_bg", 40, 40)
        self.tex("circle_error_dark", 40, 40)
        for nm, w, h in (
            ("circle_loading_bg", 89, 89),
            ("circle_loading_seek", 89, 89),
            ("header_ico_opt", 48, 48),
            ("header_ico_cht", 32, 32),
            ("header_ico_abt", 32, 32),
            ("titlescr_logo", 340, 60),
        ):
            if nm in self.raw:
                self.tex(nm, w, h)
        self.draw_strip("header_line", 0, 0, 1, 37, 1)
        self.draw_strip("mark_line", 0, 0, 1, 22, 1)
        for face in ("regular", "bold", "light"):
            self.cap_info(face, ROW_SIZE)
        for lab in ("Start game", "Cheats", "Online DB", "Options", "About"):
            self.text_w(lab, 12, "regular", 1)
        for items in PAD_HELP.values():
            for _, label in items:
                self.text_w(label, 16, "regular", 1)

    def run(self):
        os.makedirs(USER_DIR, exist_ok=True)
        self.first_run_unpack()
        self.reload_user()
        self.reload_online()
        self.warm()
        gc.collect()
        try:
            gc.freeze()        # long-lived objects are never scanned again -> no GC hitches
        except AttributeError:
            pass
        self.set_menu(M_MAIN)
        try:
            while self.running:
                self.handle(self.pump())
                if not self.running:
                    break
                self.draw_current()
                self.tick()
        finally:
            self.save_config()
            pygame.quit()


def main():
    try:
        App().run()
    except KeyboardInterrupt:
        sys.stderr.write("\n[artemis] Interrupted.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
