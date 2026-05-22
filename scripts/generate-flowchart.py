#!/usr/bin/env python3
"""Generate Uncle J's Refinery workflow flowchart — accurate + well-spaced."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#0d1117"
USER_C   = "#2ea043"   # green   — user / execution
HOOK_C   = "#b08800"   # amber   — hooks
SKILL_C  = "#1f6feb"   # blue    — skills / agents
ROUTE_C  = "#6e40c9"   # purple  — routing / MCP
BLOCK_C  = "#da3633"   # red     — block
CRON_C   = "#1a7f64"   # teal    — cron
ARROW_C  = "#6e7681"
TXT      = "#e6edf3"
DIM      = "#8b949e"

# ── Helpers ───────────────────────────────────────────────────────────────────
def box(ax, x, y, w, h, label, color,
        sublabel=None, fontsize=9, bold=False, radius=0.008):
    rect = FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle=f"round,pad=0.003,rounding_size={radius}",
        linewidth=1.5, edgecolor=color,
        facecolor=color + "1e", zorder=3,
    )
    ax.add_patch(rect)
    weight = "bold" if bold else "normal"
    ty = y + (h * 0.15 if sublabel else 0)
    ax.text(x, ty, label, ha="center", va="center",
            color=TXT, fontsize=fontsize, fontweight=weight,
            zorder=4, multialignment="center")
    if sublabel:
        ax.text(x, y - h * 0.28, sublabel, ha="center", va="center",
                color=DIM, fontsize=7, style="italic", zorder=4,
                multialignment="center")

def diamond(ax, x, y, w, h, label, color, fontsize=8.5):
    dx, dy = w/2, h/2
    xs = [x, x+dx, x, x-dx, x]
    ys = [y+dy, y, y-dy, y, y+dy]
    ax.fill(xs, ys, color=color+"1e", zorder=3)
    ax.plot(xs, ys, color=color, linewidth=1.5, zorder=3)
    ax.text(x, y, label, ha="center", va="center",
            color=TXT, fontsize=fontsize, fontweight="bold",
            zorder=4, multialignment="center")

def arrow(ax, x1, y1, x2, y2, label="", color=ARROW_C, rad=0.0):
    ax.annotate("",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="-|>", color=color, lw=1.3,
            connectionstyle=f"arc3,rad={rad}",
        ), zorder=2)
    if label:
        mx = (x1+x2)/2 + 0.012
        my = (y1+y2)/2
        ax.text(mx, my, label, ha="left", va="center",
                color=DIM, fontsize=7.5, zorder=5)

def horiz_arrow(ax, x1, y, x2, color=ARROW_C, label="", label_above=True):
    ax.annotate("",
        xy=(x2, y), xytext=(x1, y),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.2,
                        connectionstyle="arc3,rad=0.0"), zorder=2)
    if label:
        lx = (x1+x2)/2
        ly = y + (0.008 if label_above else -0.008)
        ax.text(lx, ly, label, ha="center", va="bottom" if label_above else "top",
                color=DIM, fontsize=7.5, zorder=5)

def section_tag(ax, y, text):
    ax.text(0.012, y, text, ha="left", va="center",
            color=DIM, fontsize=6.8, style="italic",
            fontfamily="monospace", zorder=5)

# ── Figure ────────────────────────────────────────────────────────────────────
FW, FH = 20, 44
fig, ax = plt.subplots(figsize=(FW, FH))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

CX  = 0.50   # main spine x
W   = 0.32   # standard box width
H   = 0.026  # standard box height
DW  = 0.22   # diamond width
DH  = 0.032  # diamond height
GAP = 0.034  # standard vertical gap between box centres

# ── Y positions — generous spacing ────────────────────────────────────────────
# Work top-down, tracking current y
y = 0.970

TITLE_Y = y;        y -= 0.030
SUBTITLE_Y = y;     y -= 0.036

# SESSION START section
SS_LABEL_Y = y;     y -= 0.002
SS_BOX_Y = y;       y -= GAP + 0.010

# USER MESSAGE
MSG_Y = y;          y -= GAP + 0.008

# UPS HOOK
UPS_Y = y;          y -= GAP + 0.006

# Blocked branch is off to the side at UPS_Y

# PRIOR ART
PA_Y = y;           y -= GAP + 0.006

# ROUTING
RT_Y = y;           y -= DH + 0.022

# MCP TOOLS ROW
MCP_Y = y;          y -= 0.060 + 0.018

# PRE-TOOL HOOKS
PTU_Y = y;          y -= GAP + 0.006

# EDIT/WRITE GATE
EW_Y = y;           y -= DH + 0.018

# JUDGE
JG_Y = y;           y -= GAP + 0.004

# SPECIALIST AGENTS
SA_Y = y;           y -= GAP + 0.006

# VERDICT
VD_Y = y;           y -= DH + 0.018

# TOOL EXECUTES
TE_Y = y;           y -= GAP + 0.008

# POST TOOL — split into two rows
PT1_Y = y;          y -= GAP + 0.004   # jcodemunch reindex (Edit/Write)
PT2_Y = y;          y -= GAP + 0.008   # injection defender (Read/Bash/mcp)

# RESPONSE
RS_Y = y;           y -= GAP + 0.014

# ── STOP HOOKS (4 boxes) ──────────────────────────────────────────────────────
STOP_LABEL_Y = y;   y -= 0.002
SH1_Y = y;          y -= GAP + 0.004   # langfuse
SH2_Y = y;          y -= GAP + 0.004   # session-notify (Telegram)
SH3_Y = y;          y -= GAP + 0.004   # mempalace convo mine
SH4_Y = y;          y -= GAP + 0.016   # skill-suggest + skill-link unlink

# CRON section
CRON_LABEL_Y = y;   y -= 0.004
CRON_Y = y;         y -= 0.058

LEGEND_Y = y - 0.010
FOOTER_Y = 0.008

# ── TITLE ─────────────────────────────────────────────────────────────────────
ax.text(CX, TITLE_Y, "Uncle J's Refinery",
        ha="center", va="center", color=TXT,
        fontsize=22, fontweight="bold", zorder=5)
ax.text(CX, SUBTITLE_Y + 0.006, "End-to-end workflow — every Claude Code session",
        ha="center", va="center", color=DIM, fontsize=11, zorder=5)

# ── SESSION START ─────────────────────────────────────────────────────────────
section_tag(ax, SS_BOX_Y, "SESSION START")
box(ax, CX, SS_BOX_Y, W + 0.06, H + 0.008,
    "SessionStart hooks fire",
    HOOK_C, fontsize=9.5,
    sublabel="healthcheck context injected  |  skill-link: project skills symlinked  |  MemPalace project mining")

arrow(ax, CX, SS_BOX_Y - (H+0.008)/2, CX, MSG_Y + H/2)

# ── USER MESSAGE ──────────────────────────────────────────────────────────────
section_tag(ax, MSG_Y, "USER INPUT")
box(ax, CX, MSG_Y, W, H,
    "User sends message to Claude Code",
    USER_C, bold=True, fontsize=10.5)

arrow(ax, CX, MSG_Y - H/2, CX, UPS_Y + H/2)

# ── USERPROMPTSUBMIT ──────────────────────────────────────────────────────────
section_tag(ax, UPS_Y, "HOOK")
box(ax, CX, UPS_Y, W, H,
    "UserPromptSubmit hook fires",
    HOOK_C, sublabel="scan-secrets.sh — blocks hardcoded credentials before model sees input")

# Blocked branch
BLK_X = 0.84
box(ax, BLK_X, UPS_Y, 0.20, H,
    "BLOCKED",
    BLOCK_C, bold=True, sublabel="secret detected")
horiz_arrow(ax, CX + W/2, UPS_Y, BLK_X - 0.10, color=BLOCK_C, label="secret found")

arrow(ax, CX, UPS_Y - H/2, CX, PA_Y + H/2)

# ── PRIOR ART CHECK ───────────────────────────────────────────────────────────
section_tag(ax, PA_Y, "SKILL")
box(ax, CX, PA_Y, W + 0.02, H,
    "prior-art-check skill invoked",
    SKILL_C,
    sublabel="MemPalace search — 'have we solved this before?' — surfaces prior decisions + context")

arrow(ax, CX, PA_Y - H/2, CX, RT_Y + DH/2)

# ── ROUTING POLICY ────────────────────────────────────────────────────────────
section_tag(ax, RT_Y, "ROUTING")
diamond(ax, CX, RT_Y, DW, DH, "CLAUDE.md\nRouting Policy", ROUTE_C)

arrow(ax, CX, RT_Y - DH/2, CX, MCP_Y + 0.042)

# ── MCP TOOLS PANEL ───────────────────────────────────────────────────────────
section_tag(ax, MCP_Y, "MCP STACK")

TOOLS = [
    ("jCodeMunch\nsymbols · blast radius\ncall graph · hotspots", ROUTE_C),
    ("jDataMunch\nCSV · Parquet\nSQL aggregation",                ROUTE_C),
    ("jDocMunch\nproject docs\nrunbooks · markdown",              ROUTE_C),
    ("MemPalace\nprior art · decisions\nsession snapshots",       SKILL_C),
    ("Serena\nLSP · cross-file refs\ntype resolution",            ROUTE_C),
    ("Context7\n3rd-party library\ndocs (version-pinned)",        ROUTE_C),
    ("DuckDB\nParquet · S3 · JSON\ncomplex SQL joins",            ROUTE_C),
]
n = len(TOOLS)
TW = 0.115
TH = 0.058
pad = 0.008
total_w = n * TW + (n-1) * pad
start_x = CX - total_w/2 + TW/2

for i, (label, color) in enumerate(TOOLS):
    tx = start_x + i * (TW + pad)
    box(ax, tx, MCP_Y, TW, TH, label, color, fontsize=7.5)
    # fan-in from routing
    ax.annotate("",
        xy=(tx, MCP_Y + TH/2),
        xytext=(CX, RT_Y - DH/2),
        arrowprops=dict(arrowstyle="-|>", color=ROUTE_C+"66",
                        lw=0.8, connectionstyle="arc3,rad=0.0"), zorder=2)
    # fan-out to PreToolUse
    ax.annotate("",
        xy=(CX, PTU_Y + H/2),
        xytext=(tx, MCP_Y - TH/2),
        arrowprops=dict(arrowstyle="-|>", color=ROUTE_C+"66",
                        lw=0.8, connectionstyle="arc3,rad=0.0"), zorder=2)

# ── PRE-TOOL HOOKS ────────────────────────────────────────────────────────────
section_tag(ax, PTU_Y, "HOOK")
box(ax, CX, PTU_Y, W + 0.04, H,
    "PreToolUse hooks fire",
    HOOK_C,
    sublabel="enforce-docs (Bash)  |  scan-commit (Bash)  |  bash-guard rules  |  jCodeMunch pre-hook (Read)")

arrow(ax, CX, PTU_Y - H/2, CX, EW_Y + DH/2)

# ── EDIT / WRITE GATE ─────────────────────────────────────────────────────────
section_tag(ax, EW_Y, "GUARD")
diamond(ax, CX, EW_Y, DW, DH, "About to Edit\nor Write?", SKILL_C)

# No → skip to tool_exec via right bypass
NO_X = 0.84
arrow(ax, CX + DW/2, EW_Y, NO_X, EW_Y,
      label="no", color=USER_C)
ax.annotate("",
    xy=(NO_X, TE_Y + H/2),
    xytext=(NO_X, EW_Y),
    arrowprops=dict(arrowstyle="-|>", color=USER_C, lw=1.2,
                    connectionstyle="arc3,rad=0.0"), zorder=2)
ax.annotate("",
    xy=(CX + W/2, TE_Y),
    xytext=(NO_X, TE_Y),
    arrowprops=dict(arrowstyle="-|>", color=USER_C, lw=1.2,
                    connectionstyle="arc3,rad=0.0"), zorder=2)

# Yes ↓ judge
arrow(ax, CX, EW_Y - DH/2, CX, JG_Y + H/2, label="yes")

# ── JUDGE SKILL ───────────────────────────────────────────────────────────────
section_tag(ax, JG_Y, "SKILL")
box(ax, CX, JG_Y, W + 0.02, H,
    "judge skill fires",
    SKILL_C,
    sublabel="blast radius · changed symbols · PR risk score via jCodeMunch")

arrow(ax, CX, JG_Y - H/2, CX, SA_Y + H/2)

# ── SPECIALIST AGENTS ─────────────────────────────────────────────────────────
section_tag(ax, SA_Y, "AGENTS")
box(ax, CX, SA_Y, W + 0.06, H,
    "Specialist agent spawned (optional delegation)",
    SKILL_C,
    sublabel="code-reviewer  |  security-reviewer  |  silent-failure-hunter  |  architect  |  planner  |  tdd-guide")

arrow(ax, CX, SA_Y - H/2, CX, VD_Y + DH/2)

# ── VERDICT ───────────────────────────────────────────────────────────────────
diamond(ax, CX, VD_Y, DW, DH, "Verdict?", SKILL_C)

# Block branch left
BLK2_X = 0.16
box(ax, BLK2_X, VD_Y, 0.20, H,
    "EDIT BLOCKED",
    BLOCK_C, bold=True, sublabel="CRITICAL issue found")
horiz_arrow(ax, CX - DW/2, VD_Y, BLK2_X + 0.10, color=BLOCK_C, label="block")

# Approve ↓ tool exec
arrow(ax, CX, VD_Y - DH/2, CX, TE_Y + H/2, label="approve / warn")

# ── TOOL EXECUTES ─────────────────────────────────────────────────────────────
section_tag(ax, TE_Y, "EXECUTE")
box(ax, CX, TE_Y, W, H,
    "Tool executes",
    USER_C, bold=True, fontsize=10,
    sublabel="Edit  |  Write  |  Bash  |  MCP call")

arrow(ax, CX, TE_Y - H/2, CX, PT1_Y + H/2)

# ── POST-TOOL HOOK 1: jCodemunch auto-reindex (Edit/Write only) ───────────────
section_tag(ax, PT1_Y, "HOOK")
box(ax, CX, PT1_Y, W + 0.04, H,
    "PostToolUse: jCodemunch auto-reindex",
    HOOK_C,
    sublabel="fires on Edit / Write — invalidates BM25 + semantic caches immediately")

arrow(ax, CX, PT1_Y - H/2, CX, PT2_Y + H/2)

# ── POST-TOOL HOOK 2: injection defender (Read/WebFetch/Bash/mcp) ────────────
box(ax, CX, PT2_Y, W + 0.04, H,
    "PostToolUse: prompt-injection defender",
    HOOK_C,
    sublabel="fires on Read / WebFetch / Bash / mcp — scans tool output for embedded commands")

arrow(ax, CX, PT2_Y - H/2, CX, RS_Y + H/2)

# ── RESPONSE ─────────────────────────────────────────────────────────────────
section_tag(ax, RS_Y, "OUTPUT")
box(ax, CX, RS_Y, W, H,
    "Response delivered to user",
    USER_C, bold=True, fontsize=10.5)

arrow(ax, CX, RS_Y - H/2, CX, SH1_Y + H/2)

# ── STOP HOOKS ────────────────────────────────────────────────────────────────
section_tag(ax, SH1_Y + 0.006, "SESSION END")

box(ax, CX, SH1_Y, W + 0.04, H,
    "Stop hook: Langfuse trace submitted",
    HOOK_C, sublabel="full session trace + AGENT_ROLE tags written to Langfuse for observability")

arrow(ax, CX, SH1_Y - H/2, CX, SH2_Y + H/2)

box(ax, CX, SH2_Y, W + 0.04, H,
    "Stop hook: session-notify.sh",
    HOOK_C, sublabel="Telegram notification sent to approval channel (opt-in: CLAUDE_NOTIFY_ON_STOP=1)")

arrow(ax, CX, SH2_Y - H/2, CX, SH3_Y + H/2)

box(ax, CX, SH3_Y, W + 0.04, H,
    "Stop hook: MemPalace convo mining",
    SKILL_C, sublabel="session transcript mined into palace drawers — feeds next session's prior-art-check")

arrow(ax, CX, SH3_Y - H/2, CX, SH4_Y + H/2)

box(ax, CX, SH4_Y, W + 0.06, H,
    "Stop hooks: auto-skill + skill-link unlink",
    SKILL_C,
    sublabel="skill-suggest.sh drafts SKILL.md → Telegram pitch  |  skill-link removes per-project symlinks")

arrow(ax, CX, SH4_Y - H/2, CX, CRON_Y + 0.038)

# ── CRON JOBS ─────────────────────────────────────────────────────────────────
section_tag(ax, CRON_LABEL_Y, "BACKGROUND CRONS  (always running, independent of sessions)")

CRONS = [
    ("01:00 daily\njCodemunch\nreindex",         CRON_C),
    ("03:00 daily\nauto-maintain\nupgrade + sync",CRON_C),
    ("07:00 daily\nhealthcheck\n+ Telegram alert",CRON_C),
    ("Daily\ndreaming\ntrace mining",             CRON_C),
    ("Weekly\nsession-stats\nreport",             CRON_C),
]
nc = len(CRONS)
CW = 0.148
CH = 0.058
cpad = 0.010
ctotal = nc * CW + (nc-1) * cpad
cstart = CX - ctotal/2 + CW/2

for i, (label, color) in enumerate(CRONS):
    cx = cstart + i * (CW + cpad)
    box(ax, cx, CRON_Y, CW, CH, label, color, fontsize=8)

# dashed border around cron zone
cron_rect = FancyBboxPatch(
    (0.018, CRON_Y - CH/2 - 0.012), 0.964, CH + 0.036,
    boxstyle="round,pad=0.004,rounding_size=0.008",
    linewidth=1.1, edgecolor=CRON_C + "77", facecolor="none",
    linestyle="dashed", zorder=2,
)
ax.add_patch(cron_rect)

# ── LEGEND ────────────────────────────────────────────────────────────────────
LEG_X = 0.025
LEG_Y = LEGEND_Y
ax.text(LEG_X, LEG_Y + 0.018, "Legend",
        color=DIM, fontsize=8.5, fontweight="bold", zorder=5)

leg = [
    (USER_C,  "User interaction / execution"),
    (HOOK_C,  "Hook (automatic)"),
    (SKILL_C, "Skill / Agent"),
    (ROUTE_C, "MCP tool / routing"),
    (BLOCK_C, "Block / error path"),
    (CRON_C,  "Background cron job"),
]
for i, (color, label) in enumerate(leg):
    col = i % 3
    row = i // 3
    lx = LEG_X + col * 0.31
    ly = LEG_Y - row * 0.018
    swatch = FancyBboxPatch(
        (lx, ly - 0.006), 0.020, 0.013,
        boxstyle="round,pad=0.002,rounding_size=0.003",
        linewidth=1, edgecolor=color,
        facecolor=color + "33", zorder=5)
    ax.add_patch(swatch)
    ax.text(lx + 0.026, ly, label,
            color=TXT, fontsize=8, va="center", zorder=5)

# ── FOOTER ────────────────────────────────────────────────────────────────────
ax.text(CX, FOOTER_Y,
        "Uncle J's Refinery  —  github.com/williamblair333/Uncle-J-s-Refinery",
        ha="center", va="center", color=DIM, fontsize=8, zorder=5)

# ── SAVE ──────────────────────────────────────────────────────────────────────
out = "/opt/proj/Uncle-J-s-Refinery/docs/uncle-js-flowchart.png"
fig.savefig(out, dpi=180, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
print(f"Saved: {out}")
