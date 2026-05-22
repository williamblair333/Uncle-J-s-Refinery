#!/usr/bin/env python3
"""Generate Uncle J's Refinery workflow flowchart using matplotlib."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

# ── Palette ──────────────────────────────────────────────────────────────────
BG          = "#0d1117"
USER_C      = "#238636"   # green  — user / output
HOOK_C      = "#b08800"   # amber  — hooks
SKILL_C     = "#1f6feb"   # blue   — skills / agents
ROUTE_C     = "#6e40c9"   # purple — routing / MCP tools
BLOCK_C     = "#da3633"   # red    — block / danger
CRON_C      = "#1a7f64"   # teal   — background cron jobs
ARROW_C     = "#8b949e"
TEXT_LIGHT  = "#e6edf3"
TEXT_DIM    = "#8b949e"
BORDER_DIM  = "#30363d"

FIG_W, FIG_H = 18, 28

def box(ax, x, y, w, h, label, color, text_color=TEXT_LIGHT,
        fontsize=9.5, bold=False, sublabel=None, radius=0.012):
    rect = FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle=f"round,pad=0.005,rounding_size={radius}",
        linewidth=1.4, edgecolor=color,
        facecolor=color + "22", zorder=3,
    )
    ax.add_patch(rect)
    weight = "bold" if bold else "normal"
    ty = y + (h * 0.12 if sublabel else 0)
    ax.text(x, ty, label, ha="center", va="center",
            color=text_color, fontsize=fontsize, fontweight=weight,
            zorder=4, wrap=True,
            multialignment="center")
    if sublabel:
        ax.text(x, y - h * 0.22, sublabel, ha="center", va="center",
                color=TEXT_DIM, fontsize=7.5, style="italic", zorder=4,
                multialignment="center")

def diamond(ax, x, y, w, h, label, color, fontsize=8.5):
    dx, dy = w/2, h/2
    xs = [x, x+dx, x, x-dx, x]
    ys = [y+dy, y, y-dy, y, y+dy]
    ax.fill(xs, ys, color=color+"22", zorder=3)
    ax.plot(xs, ys, color=color, linewidth=1.4, zorder=3)
    ax.text(x, y, label, ha="center", va="center",
            color=TEXT_LIGHT, fontsize=fontsize, fontweight="bold",
            zorder=4, multialignment="center")

def arrow(ax, x1, y1, x2, y2, label="", color=ARROW_C, style="-|>"):
    ax.annotate("",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle=style, color=color,
            lw=1.3, connectionstyle="arc3,rad=0.0",
        ), zorder=2)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx+0.015, my, label, ha="left", va="center",
                color=TEXT_DIM, fontsize=7.5, zorder=4)

def curved_arrow(ax, x1, y1, x2, y2, rad=0.3, color=ARROW_C, label=""):
    ax.annotate("",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="-|>", color=color, lw=1.2,
            connectionstyle=f"arc3,rad={rad}",
        ), zorder=2)
    if label:
        mx, my = (x1+x2)/2 + 0.04, (y1+y2)/2
        ax.text(mx, my, label, ha="left", va="center",
                color=TEXT_DIM, fontsize=7.5, zorder=4)

def section_label(ax, x, y, text):
    ax.text(x, y, text, ha="left", va="center",
            color=TEXT_DIM, fontsize=7, style="italic",
            fontfamily="monospace", zorder=4)

# ── Figure setup ─────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

CX = 0.5   # centre x of main spine
W  = 0.30  # standard box width
H  = 0.032 # standard box height
DW = 0.22  # diamond width
DH = 0.038 # diamond height

# ── Title ─────────────────────────────────────────────────────────────────────
ax.text(CX, 0.975, "Uncle J's Refinery", ha="center", va="center",
        color=TEXT_LIGHT, fontsize=20, fontweight="bold", zorder=4)
ax.text(CX, 0.958, "End-to-end workflow — every Claude Code session",
        ha="center", va="center", color=TEXT_DIM, fontsize=10, zorder=4)

# ── Main spine Y positions (top → bottom) ────────────────────────────────────
Y = {
    "user_msg":     0.920,
    "ups_hook":     0.875,
    "inject_block": 0.850,   # branch: blocked
    "prior_art":    0.820,
    "routing":      0.768,
    "mcp_tools":    0.718,
    "edit_gate":    0.665,
    "judge":        0.640,
    "agent_review": 0.615,
    "block_or_go":  0.580,
    "tool_exec":    0.545,
    "post_hook":    0.505,
    "response":     0.462,
    "stop_hooks":   0.415,
    "telegram":     0.375,
    "mempalace":    0.345,
    "autoskill":    0.315,
}

# ── 1. User message ───────────────────────────────────────────────────────────
box(ax, CX, Y["user_msg"], W, H,
    "User sends message to Claude Code", USER_C, bold=True, fontsize=10)

arrow(ax, CX, Y["user_msg"]-H/2, CX, Y["ups_hook"]+H/2)
section_label(ax, 0.025, (Y["user_msg"]+Y["ups_hook"])/2, "HOOKS")

# ── 2. UserPromptSubmit hook ──────────────────────────────────────────────────
box(ax, CX, Y["ups_hook"], W, H,
    "UserPromptSubmit hook fires",
    HOOK_C, sublabel="secret scanner + injection defender (dwarvesf guardrails)")

arrow(ax, CX, Y["ups_hook"]-H/2, CX, Y["routing"]+DH/2)

# ── 2a. Injection blocked branch ─────────────────────────────────────────────
BX = 0.80
box(ax, BX, Y["inject_block"], 0.20, H,
    "BLOCKED", BLOCK_C, bold=True,
    sublabel="secret / injection detected")
curved_arrow(ax, CX+W/2, Y["ups_hook"], BX-0.10, Y["inject_block"], rad=-0.25,
             color=BLOCK_C, label="detected")

# ── 3. Routing decision ───────────────────────────────────────────────────────
section_label(ax, 0.025, (Y["ups_hook"]+Y["routing"])/2, "ROUTING")
diamond(ax, CX, Y["routing"], DW, DH,
        "CLAUDE.md\nRouting Policy", ROUTE_C)

arrow(ax, CX, Y["routing"]-DH/2, CX, Y["mcp_tools"]+H/2)

# ── 4. MCP tool panel ─────────────────────────────────────────────────────────
section_label(ax, 0.025, (Y["routing"]+Y["mcp_tools"])/2, "MCP STACK")

TOOLS = [
    ("jCodeMunch\nsymbols · blast radius\ncall graph · hotspots",   ROUTE_C, 0.13),
    ("jDataMunch\nCSV · Parquet\nSQL aggregation",                   ROUTE_C, 0.29),
    ("jDocMunch\nproject docs\nrunbooks · markdown",                 ROUTE_C, 0.45),
    ("MemPalace\nprior art · decisions\nsession snapshots",          SKILL_C, 0.61),
    ("Serena\nLSP · cross-file refs\ntype resolution",               ROUTE_C, 0.77),
    ("Context7\n3rd-party library\ndocs (version-pinned)",           ROUTE_C, 0.87),
]

TH, TW = 0.075, 0.115
for label, color, tx in TOOLS:
    box(ax, tx, Y["mcp_tools"], TW, TH, label, color, fontsize=7.5)
    ax.annotate("",
        xy=(tx, Y["mcp_tools"]+TH/2), xytext=(CX, Y["routing"]-DH/2),
        arrowprops=dict(arrowstyle="-|>", color=ROUTE_C+"88",
                        lw=0.9, connectionstyle="arc3,rad=0.0"), zorder=2)
    ax.annotate("",
        xy=(CX, Y["edit_gate"]+DH/2), xytext=(tx, Y["mcp_tools"]-TH/2),
        arrowprops=dict(arrowstyle="-|>", color=ROUTE_C+"88",
                        lw=0.9, connectionstyle="arc3,rad=0.0"), zorder=2)

# ── 5. Edit/Write gate ────────────────────────────────────────────────────────
section_label(ax, 0.025, (Y["mcp_tools"]+Y["edit_gate"])/2, "GUARD")
diamond(ax, CX, Y["edit_gate"], DW, DH,
        "About to Edit\nor Write?", SKILL_C)

# No-branch → tool_exec
NX = 0.78
arrow(ax, CX+DW/2, Y["edit_gate"], NX, Y["edit_gate"],
      label="no", color=USER_C)
ax.annotate("",
    xy=(NX, Y["tool_exec"]+H/2), xytext=(NX, Y["edit_gate"]),
    arrowprops=dict(arrowstyle="-|>", color=USER_C, lw=1.2,
                    connectionstyle="arc3,rad=0.0"), zorder=2)
ax.annotate("",
    xy=(CX+W/2, Y["tool_exec"]), xytext=(NX, Y["tool_exec"]),
    arrowprops=dict(arrowstyle="-|>", color=USER_C, lw=1.2,
                    connectionstyle="arc3,rad=0.0"), zorder=2)

# Yes-branch ↓ judge
arrow(ax, CX, Y["edit_gate"]-DH/2, CX, Y["judge"]+H/2, label="yes")

# ── 6. Judge skill ────────────────────────────────────────────────────────────
box(ax, CX, Y["judge"], W, H,
    "judge skill fires",
    SKILL_C, sublabel="blast radius · changed symbols · PR risk from jCodeMunch")

arrow(ax, CX, Y["judge"]-H/2, CX, Y["agent_review"]+H/2)

# ── 7. Specialist agents (optional delegation) ────────────────────────────────
box(ax, CX, Y["agent_review"], W+0.04, H,
    "Specialist agent spawned (optional)",
    SKILL_C,
    sublabel="code-reviewer · security-reviewer · silent-failure-hunter · architect · planner · tdd-guide")

arrow(ax, CX, Y["agent_review"]-H/2, CX, Y["block_or_go"]+DH/2)

# ── 8. Approve / block decision ───────────────────────────────────────────────
diamond(ax, CX, Y["block_or_go"], DW, DH,
        "Verdict?", SKILL_C)

# block branch
box(ax, 0.18, Y["block_or_go"], 0.18, H,
    "EDIT BLOCKED", BLOCK_C, bold=True,
    sublabel="CRITICAL issue found")
arrow(ax, CX-DW/2, Y["block_or_go"], 0.27, Y["block_or_go"],
      label="block", color=BLOCK_C)

# approve → tool_exec
arrow(ax, CX, Y["block_or_go"]-DH/2, CX, Y["tool_exec"]+H/2,
      label="approve / warn")

# ── 9. Tool executes ──────────────────────────────────────────────────────────
section_label(ax, 0.025, (Y["block_or_go"]+Y["tool_exec"])/2, "EXECUTE")
box(ax, CX, Y["tool_exec"], W, H,
    "Tool executes", USER_C, bold=True,
    sublabel="Edit · Write · Bash · MCP call")

arrow(ax, CX, Y["tool_exec"]-H/2, CX, Y["post_hook"]+H/2)

# ── 10. PostToolUse hook ──────────────────────────────────────────────────────
section_label(ax, 0.025, (Y["tool_exec"]+Y["post_hook"])/2, "HOOKS")
box(ax, CX, Y["post_hook"], W, H,
    "PostToolUse hook fires",
    HOOK_C, sublabel="scan tool output for prompt-injection attempts")

arrow(ax, CX, Y["post_hook"]-H/2, CX, Y["response"]+H/2)

# ── 11. Response ──────────────────────────────────────────────────────────────
box(ax, CX, Y["response"], W, H,
    "Response delivered to user", USER_C, bold=True, fontsize=10)

arrow(ax, CX, Y["response"]-H/2, CX, Y["stop_hooks"]+H/2)

# ── 12. Stop hooks ────────────────────────────────────────────────────────────
section_label(ax, 0.025, (Y["response"]+Y["stop_hooks"])/2, "SESSION END")
box(ax, CX, Y["stop_hooks"], W, H,
    "Stop hooks fire",
    HOOK_C, sublabel="jCodemunch reindex · session notify")

arrow(ax, CX, Y["stop_hooks"]-H/2, CX, Y["telegram"]+H/2)
box(ax, CX, Y["telegram"], W, H,
    "Telegram notification sent",
    HOOK_C, sublabel="session summary → approval channel")

arrow(ax, CX, Y["telegram"]-H/2, CX, Y["mempalace"]+H/2)
box(ax, CX, Y["mempalace"], W, H,
    "MemPalace convo mining",
    SKILL_C, sublabel="session → drawer snapshots for next session's prior-art-check")

arrow(ax, CX, Y["mempalace"]-H/2, CX, Y["autoskill"]+H/2)
box(ax, CX, Y["autoskill"], W, H,
    "Auto-skill drafting",
    SKILL_C, sublabel="transcript analysed → SKILL.md drafted → Telegram pitch for approval")

# ── 13. Background crons panel ───────────────────────────────────────────────
CRON_Y = 0.230
ax.text(CX, CRON_Y+0.045, "Background cron jobs (always running)",
        ha="center", va="center", color=TEXT_DIM, fontsize=8,
        style="italic", zorder=4)

CRONS = [
    ("01:00 daily\njCodemunch\nreindex", 0.13),
    ("03:00 daily\nauto-maintain\nupgrade + sync", 0.35),
    ("07:00 daily\nhealthcheck\n+ Telegram alert", 0.57),
    ("Daily\ndreaming\ntrace mining", 0.79),
]
CH, CW = 0.068, 0.155
for label, cx in CRONS:
    box(ax, cx, CRON_Y, CW, CH, label, CRON_C, fontsize=7.5)

# dashed border around cron section
from matplotlib.patches import Rectangle
cron_rect = FancyBboxPatch(
    (0.02, CRON_Y - CH/2 - 0.01), 0.96, CH + 0.065,
    boxstyle="round,pad=0.005,rounding_size=0.01",
    linewidth=1, edgecolor=CRON_C+"66", facecolor="none",
    linestyle="dashed", zorder=2,
)
ax.add_patch(cron_rect)

# ── 14. Prior-art-check detail: feeds back to top ────────────────────────────
# small annotation on prior-art box
PA_Y = Y["routing"] + 0.035
box(ax, CX, PA_Y, W+0.02, H*0.85,
    "prior-art-check skill fires first",
    SKILL_C, fontsize=8.5,
    sublabel="MemPalace search → surfaces prior decisions before any tool call")
arrow(ax, CX, PA_Y - H*0.85/2, CX, Y["routing"]+DH/2)
arrow(ax, CX, Y["ups_hook"]-H/2, CX, PA_Y+H*0.85/2)

# ── Legend ────────────────────────────────────────────────────────────────────
LEG_X, LEG_Y = 0.025, 0.135
leg_items = [
    (USER_C,  "User interaction / execution"),
    (HOOK_C,  "Hook (automatic, every turn)"),
    (SKILL_C, "Skill / Agent"),
    (ROUTE_C, "MCP tool / routing"),
    (BLOCK_C, "Block / error path"),
    (CRON_C,  "Background cron job"),
]
ax.text(LEG_X, LEG_Y+0.025, "Legend", color=TEXT_DIM,
        fontsize=8, fontweight="bold", zorder=4)
for i, (color, label) in enumerate(leg_items):
    lx = LEG_X + (i % 3) * 0.30
    ly = LEG_Y - (i // 3) * 0.022
    rect = FancyBboxPatch((lx, ly-0.007), 0.018, 0.014,
                          boxstyle="round,pad=0.002,rounding_size=0.003",
                          linewidth=1, edgecolor=color,
                          facecolor=color+"33", zorder=4)
    ax.add_patch(rect)
    ax.text(lx+0.024, ly, label, color=TEXT_LIGHT,
            fontsize=7.5, va="center", zorder=4)

# ── Footer ────────────────────────────────────────────────────────────────────
ax.text(CX, 0.012, "Uncle J's Refinery  ·  github.com/williamblair333/Uncle-J-s-Refinery",
        ha="center", va="center", color=TEXT_DIM, fontsize=7.5, zorder=4)

out = "/opt/proj/Uncle-J-s-Refinery/docs/uncle-js-flowchart.png"
fig.savefig(out, dpi=180, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
print(f"Saved: {out}")
