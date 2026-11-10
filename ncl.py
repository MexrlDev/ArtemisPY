# Artemis PS3 cheat file (.ncl) parser and game list scanner.
# Port of ReadNCL()/ReadOptionFromLine()/LoadGames() from ArtemisPS3-GUI (codes.c).
# Original Artemis: Berion, NzV, Dnawrkshp, Bucanero. Python port: MexrlDev 2025.
import os
import re

TID_RE = re.compile(r"^[A-Z]{4}\d{5}$")
VER_RE = re.compile(r"^v?\d{2}\.\d{2}$", re.I)
CODE_RE = re.compile(r"^[0-9A-Fa-f]\s+[0-9A-Fa-f]{4,}")
OPT_RE = re.compile(r"^\[(\w)\](.*)\[/\1\]\s*$")


class Option:
    """A [Z]VALUE=Name;VALUE=Name[/Z] choice. `letter` is the placeholder used in code lines."""

    def __init__(self, letter, values, names):
        self.letter = letter
        self.values = values
        self.names = names
        self.sel = 0


class Code:
    def __init__(self, name, cwrite, author, lines, options):
        self.name = name
        self.cwrite = cwrite  # True = "constant", False = "once"
        self.author = author
        self.lines = lines
        self.options = options
        self.activated = False

    def resolved_lines(self):
        """Code lines with option placeholders replaced by the chosen values."""
        out = []
        for line in self.lines:
            toks = line.split(" ")
            for opt in self.options:
                if not opt.values:
                    continue
                val = opt.values[min(opt.sel, len(opt.values) - 1)]
                hexlike = opt.letter.upper() in "0123456789ABCDEF"
                for i in range(1, len(toks)):
                    if hexlike:  # ambiguous with real hex digits: only replace a lone placeholder token
                        if toks[i] == opt.letter:
                            toks[i] = val
                    else:
                        toks[i] = toks[i].replace(opt.letter, val)
            out.append(" ".join(toks))
        return out


class Game:
    def __init__(self, name, title_ids, version, path):
        self.name = name
        self.title_ids = title_ids
        self.version = version
        self.path = path
        self.codes = None  # loaded lazily

    @property
    def title_id(self):
        return self.title_ids[0] if self.title_ids else ""


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _parse_options(line):
    m = OPT_RE.match(line.strip())
    if not m:
        return None
    values, names = [], []
    for part in m.group(2).split(";"):
        if "=" in part:
            v, n = part.split("=", 1)
            values.append(v.strip())
            names.append(n.strip())
    return Option(m.group(1), values, names) if names else None


def _make_code(buf, old_format):
    buf = [b for b in buf]
    if len(buf) < 2:
        return None
    if old_format:
        cw, name = buf[0], buf[1]
    else:
        name, cw = buf[0], buf[1]
    name = name.strip()
    if not name:
        return None
    cwrite = cw.strip()[:1] in ("1", "T", "t")
    author, lines, options = "", [], []
    for raw in buf[2:]:
        s = raw.strip()
        if not s:
            continue
        opt = _parse_options(s)
        if opt:
            options.append(opt)
        elif CODE_RE.match(s) or s[:2] in ("1 ", "2 "):
            lines.append(s)
        elif not author and not lines:
            author = s
    return Code(name, cwrite, author, lines, options)


def read_ncl(path):
    """Parse a .ncl file. Returns a list of Code (empty list on failure)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    text = _strip_comments(text.replace("\r\n", "\n").replace("\r", "\n"))
    codes, buf, old = [], [], False
    for line in text.split("\n"):
        s = line.strip()
        if s == "{":
            buf, old = [], True
        elif s.startswith("#") or s.startswith("}"):
            code = _make_code(buf, old)
            if code:
                codes.append(code)
            buf, old = [], s.startswith("}") and False
        else:
            buf.append(line)
    return codes


def parse_filename(fname):
    """'Name BLES01475 01.00.ncl' -> (name, [title ids], version)."""
    stem = os.path.splitext(fname)[0]
    toks = stem.split(" ")
    ids = [t for t in toks if TID_RE.match(t)]
    if ids:
        first = toks.index(ids[0])
        name = " ".join(toks[:first]).strip() or stem
    else:
        name = stem
    ver = ""
    for t in toks:
        if VER_RE.match(t):
            ver = t.lstrip("vV")
            break
    return name, ids, ver


def scan_games(folder, sort=True):
    games = []
    if not os.path.isdir(folder):
        return games
    seen = set()
    for dirpath, _, filenames in os.walk(folder):
        for fn in filenames:
            if not fn.lower().endswith(".ncl"):
                continue
            path = os.path.join(dirpath, fn)
            if path in seen:
                continue
            seen.add(path)
            name, ids, ver = parse_filename(fn)
            games.append(Game(name, ids, ver, path))
    if sort:
        games.sort(key=lambda g: (g.name.lower(), g.version, g.title_id))
    return games
