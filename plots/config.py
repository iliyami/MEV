from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "plots" / "generated"
FIGURE_DIR = GENERATED_DIR / "figures"
REPORT_DIR = GENERATED_DIR / "reports"

PROTOCOL_ORDER = [
    "narwhal",
    "bullshark",
    "mysticeti",
    "mevsui",
    "alephbft",
    "mahimahi",
    "autobahn",
]

PROTOCOL_LABELS = {
    "narwhal": "Narwhal-Tusk",
    "bullshark": "Bullshark",
    "mysticeti": "Mysticeti",
    "mevsui": "MEVSUI",
    "alephbft": "AlephBFT",
    "mahimahi": "Mahi-Mahi",
    "autobahn": "Autobahn",
}

PROTOCOL_COLORS = {
    "narwhal": "1B9E77",
    "bullshark": "D95F02",
    "mysticeti": "7570B3",
    "mevsui": "E7298A",
    "alephbft": "66A61E",
    "mahimahi": "E6AB02",
    "autobahn": "1F78B4",
}

PROTOCOL_TIKZ_COLORS = {
    "narwhal": "ProtoNarwhal",
    "bullshark": "ProtoBullshark",
    "mysticeti": "ProtoMysticeti",
    "mevsui": "ProtoMevSui",
    "alephbft": "ProtoAleph",
    "mahimahi": "ProtoMahi",
    "autobahn": "ProtoAutobahn",
}

PROTOCOL_MARKS = {
    "narwhal": "*",
    "bullshark": "square*",
    "mysticeti": "triangle*",
    "mevsui": "diamond*",
    "alephbft": "pentagon*",
    "mahimahi": "otimes*",
    "autobahn": "star",
}

ATTACK_ORDER = ["fissure", "speculative", "sluggish"]
ATTACK_LABELS = {
    "fissure": "Fissure",
    "sluggish": "Sluggish",
    "speculative": "Speculative",
}

ATTACK_COLORS = {
    "fissure": "C0392B",
    "sluggish": "2C7FB8",
    "speculative": "7B3294",
}

ATTACK_TIKZ_COLORS = {
    "fissure": "AttackFissure",
    "sluggish": "AttackSluggish",
    "speculative": "AttackSpeculative",
}

ATTACK_STYLES = {
    "fissure": "solid",
    "sluggish": "densely dashed",
    "speculative": "densely dotted",
}

ATTACK_MARKS = {
    "fissure": "square*",
    "sluggish": "triangle*",
    "speculative": "*",
}

LATENCY_ORDER = ["0ms 0ms", "50ms 10ms", "150ms 30ms", "300ms 50ms"]
LATENCY_LABELS = {
    "0ms 0ms": r"0",
    "50ms 10ms": r"50$\pm$10",
    "150ms 30ms": r"150$\pm$30",
    "300ms 50ms": r"300$\pm$50",
}

EXPERIMENT_LABELS = {
    "scaling": "Node scale",
    "scaling_workers": "Workers per node",
    "offense_fissure": "Attacker fraction",
    "offense_exclusion": "Exclusion probability",
    "offense_sluggish": "Delay multiplier",
    "offense_speculative": "Speculative grind depth",
    "env_latency": "Injected latency",
    "defense_memory": "DAG cache depth",
    "defense_gc": "GC depth",
    "defense_network": "Sync timeout",
    "defense_header": "Header parameters",
    "defense_batching": "Batch parameters",
    "mahimahi_leaders": "Leaders per wave",
    "mahimahi_wave": "Wave length",
    "mahimahi_strategy": "Speculative strategy",
    "mysticeti_strategy": "Speculative strategy",
    "aleph_lookahead": "Election lookahead",
    "aleph_sync_speed": "Coordination delay",
    "aleph_hash_randomization": "Hash seed",
    "autobahn_k": "Autobahn K",
    "autobahn_fast_path": "Fast-path timeout",
}

TIKZ_STYLE_PREAMBLE = r"""
\pgfplotsset{compat=1.18}
\usetikzlibrary{calc}
\usepgfplotslibrary{groupplots}
\usepgfplotslibrary{statistics}
\usepgfplotslibrary{colorbrewer}
\definecolor{ProtoNarwhal}{HTML}{1B9E77}
\definecolor{ProtoBullshark}{HTML}{D95F02}
\definecolor{ProtoMysticeti}{HTML}{7570B3}
\definecolor{ProtoMevSui}{HTML}{E7298A}
\definecolor{ProtoAleph}{HTML}{66A61E}
\definecolor{ProtoMahi}{HTML}{E6AB02}
\definecolor{ProtoAutobahn}{HTML}{1F78B4}
\definecolor{AttackFissure}{HTML}{C0392B}
\definecolor{AttackSluggish}{HTML}{2C7FB8}
\definecolor{AttackSpeculative}{HTML}{7B3294}
\pgfplotsset{
  mevAxis/.style={
    width=0.31\linewidth,
    height=0.24\linewidth,
    ymin=0,
    ymax=100,
    ymajorgrids=true,
    grid style={draw=black!10},
    axis line style={draw=black!55},
    tick style={draw=black!55},
    tick label style={font=\scriptsize},
    label style={font=\small},
    title style={font=\small\bfseries},
    legend style={
      font=\scriptsize,
      draw=none,
      fill=none,
      legend cell align=left,
      /tikz/every even column/.append style={column sep=0.35cm},
    },
    line width=1pt,
    mark size=2.2pt,
  },
  mevSmallAxis/.style={
    width=0.24\linewidth,
    height=0.18\linewidth,
    ymin=0,
    ymax=100,
    ymajorgrids=true,
    grid style={draw=black!10},
    axis line style={draw=black!55},
    tick style={draw=black!55},
    tick label style={font=\scriptsize},
    label style={font=\scriptsize},
    title style={font=\scriptsize\bfseries},
    line width=0.9pt,
    mark size=2pt,
    clip mode=individual,
  },
  mevBarAxis/.style={
    width=\linewidth,
    height=0.33\linewidth,
    ymin=0,
    ymajorgrids=true,
    grid style={draw=black!10},
    axis line style={draw=black!55},
    tick style={draw=black!55},
    tick label style={font=\scriptsize},
    label style={font=\small},
    title style={font=\small\bfseries},
    legend style={font=\scriptsize, draw=none, fill=none},
    bar width=7pt,
  },
  mevHeatAxis/.style={
    width=0.29\linewidth,
    height=0.25\linewidth,
    ymin=0.5,
    ymax=3.5,
    axis line style={draw=black!55},
    tick style={draw=black!55},
    tick label style={font=\scriptsize},
    label style={font=\small},
    title style={font=\small\bfseries},
    enlargelimits=false,
    y dir=reverse,
    point meta min=0,
    point meta max=100,
    colormap/viridis,
  },
}
"""
