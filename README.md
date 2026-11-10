# Artemis PS3 - PY port

Python port of the **ArtemisPS3-GUI** cheat manager. Layout, sizes, fonts and animations follow the
original PS3 source (848x512 virtual screen, Comfortaa fonts, 128-frame menu animations, sliding side panels).
Original Artemis: Berion (GUI design), NzV, Dnawrkshp (GUI/PRX), Bucanero (network code). Python port: MexrlDev.
Free to use, mod and publish with credits to the original creators.

## Run
    pip install -r requirements.txt
    python main.py

## Screens
Title (Start game / Cheats / Online DB / Options / About), User list, Online DB list, cheat list with
once/constant pills, Cheat View panel, Cheat Option panel (for codes with `[Z]..=..;..[/Z]` choices),
Options, About, controls help (F1), dialogs, loading spinner, closing animation.

## Controls
| Key | Action (PS3 button) |
|---|---|
| Arrows / mouse wheel | Move |
| Enter / left click | Select (cross) |
| Esc / Backspace / right click | Back (circle) |
| Space | Toggle once/constant, Refresh list (square) |
| T | View code, Filter list (triangle) |
| Page Up / Page Down | Previous / next letter (L1 / R1) |
| F / F11 | Fullscreen |
| F1 | Help |

## Data
* `codes/` - your own `.ncl` cheat files (12 samples included) = **Cheats / User List**.
* `online_cache/` - the cheat database (2,540 games). Unpacked from `data/cheatdb.zip` on first run;
  **Options > Update Local Cheats** downloads the latest from GitHub.
* Enabled cheats are remembered in `artemis_config.json`. **Start game** writes them to `artemis_active.txt`
  (or NCL format, see Options > Export Format). A PC cannot inject into a PS3, so this is an export.

  ## Credit
~~~  
Lazy Bastard    -   Project Founder
Berion          -   GUI Graphic Designer
Dnawrkshp       -   Creator of ArtemisPS3-GUI and ArtemisPS3-PRX
NzV             -   PS3MAPI (on which Artemis is dependant upon)
PS2Dragon       -   Artemis Logo
Bucanero        -   Network code
MexrlDev        -   Python port
~~~
  * See [LICENSE](LICENSE)
