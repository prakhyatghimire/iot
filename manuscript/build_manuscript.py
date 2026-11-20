#!/usr/bin/env python3
"""Build the IEEE-style two-column Word manuscript from verified project evidence.

Run:  .venv/bin/python manuscript/build_manuscript.py

All numbers in this document are taken from evidence/metrics/metrics_results.json
and evidence/live_cloud_coordinates.json. Author names and group number are
intentionally left as bracketed placeholders for the group to complete.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "manuscript"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
DOCX = OUT / "GroupNo_Assessment-03_Manuscript.docx"

COL_W = 3.30  # inches, usable column width


# --------------------------------------------------------------------------
# helper functions
# --------------------------------------------------------------------------
def set_run(run, size=10, bold=False, italic=False, font="Times New Roman"):
    run.font.name = font
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font)
    return run


def body(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.0
    set_run(p.add_run(text))
    return p


def heading(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    set_run(p.add_run(text), bold=True)
    return p


def subheading(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    set_run(p.add_run(text), italic=True)
    return p


def caption(doc, text, above=False):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4 if above else 2)
    p.paragraph_format.space_after = Pt(4)
    set_run(p.add_run(text), size=8, bold=above)
    return p


def figure(doc, path: Path, cap: str):
    if not path.is_file():
        raise FileNotFoundError(path)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.add_run().add_picture(str(path), width=Inches(COL_W))
    caption(doc, cap)


def table(doc, headers, rows, cap, widths=None):
    caption(doc, cap, above=True)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(p.add_run(str(h)), size=8, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            set_run(p.add_run(str(value)), size=8)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def equation(doc, text, number):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(COL_W), WD_TAB_ALIGNMENT.RIGHT)
    set_run(p.add_run(text + "\t(" + str(number) + ")"), size=9, italic=True)
    return p


def listing(doc, lines, cap):
    caption(doc, cap, above=True)
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        set_run(p.add_run(line), size=7.5, font="Courier New")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_page_number(paragraph):
    run = paragraph.add_run()
    f1 = OxmlElement("w:fldChar")
    f1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    f2 = OxmlElement("w:fldChar")
    f2.set(qn("w:fldCharType"), "end")
    run._r.append(f1)
    run._r.append(instr)
    run._r.append(f2)
    set_run(run, size=9)


# --------------------------------------------------------------------------
# architecture figure
# --------------------------------------------------------------------------
def make_architecture_figure():
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.axis("off")
    boxes = [
        (0.3, 2.0, 2.7, 2.0, "Virtual edge nodes\n(3 x Python/ESP32-S3\nsimulator)", "#dbeafe"),
        (3.7, 2.0, 2.5, 2.0, "SQLite\nstore-and-forward\n(WAL, synced flag)", "#dcfce7"),
        (6.9, 2.0, 2.7, 2.0, "MQTT / TLS :8883\nQoS 1 PUBACK\nbatched replay", "#fef3c7"),
        (10.3, 2.0, 3.4, 2.0, "ThingsBoard Cloud\ndevices, alarms\ndashboard, RPC", "#fce7f3"),
    ]
    for x, y, w, h, label, color in boxes:
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                     boxstyle="round,pad=0.08,rounding_size=0.12",
                     linewidth=1.1, edgecolor="#334155", facecolor=color))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=8.5)
    for x1, x2 in ((3.0, 3.7), (6.2, 6.9), (9.6, 10.3)):
        ax.add_patch(FancyArrowPatch((x1, 3.0), (x2, 3.0), arrowstyle="-|>",
                     mutation_scale=12, linewidth=1.2, color="#334155"))
    ax.text(5.05, 4.5, "persist first", ha="center", fontsize=7.5, color="#334155")
    ax.text(8.25, 4.5, "publish / confirm", ha="center", fontsize=7.5, color="#334155")
    ax.text(11.95, 4.5, "REST RPC scenario control", ha="center", fontsize=7.5, color="#334155")
    ax.text(7.0, 0.75, "Client-stamped payload: {ts: acquisition_ms, values: {...}} - original time preserved on replay",
            ha="center", fontsize=7.5, color="#334155")
    fig.tight_layout()
    path = FIG / "architecture.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# document setup
# --------------------------------------------------------------------------
def setup_document():
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(4)

    sec1 = doc.sections[0]
    sec1.page_width = Inches(8.5)
    sec1.page_height = Inches(11)
    for attr in ("left_margin", "right_margin"):
        setattr(sec1, attr, Inches(0.6))
    sec1.top_margin = Inches(0.6)
    sec1.bottom_margin = Inches(0.6)

    sec2 = doc.add_section(WD_SECTION.CONTINUOUS)
    sec2.page_width = Inches(8.5)
    sec2.page_height = Inches(11)
    sec2.left_margin = Inches(0.6)
    sec2.right_margin = Inches(0.6)
    sec2.top_margin = Inches(0.6)
    sec2.bottom_margin = Inches(0.6)
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), "2")
    cols.set(qn("w:space"), "360")
    sec2._sectPr.append(cols)

    for sec in doc.sections:
        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_page_number(fp)
    return doc


def build():
    arch = make_architecture_figure()

    doc = setup_document()

    # ---------------- title block (single column) ----------------
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    set_run(p.add_run(
        "Resilient Edge-to-Cloud Water Quality Monitoring for Post-Flood Nepal: "
        "Implementation and Measured Evaluation of a Three-Node Virtual IoT Fleet"
    ), size=15, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    set_run(p.add_run("[GROUP LEADER NAME], [MEMBER 2 NAME], [MEMBER 3 NAME], "
                      "[MEMBER 4 NAME], [MEMBER 5 NAME]"), size=10)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    set_run(p.add_run("School of Computer Science, [UNIVERSITY NAME]"),
            size=9, italic=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    set_run(p.add_run("[STUDENT EMAILS]  -  Group [GROUP NUMBER], ITS67404, "
                      "Assessment Task 3, September 2026 Semester"), size=8.5)

    # ---------------- abstract and keywords ----------------
    heading(doc, "Abstract-Post-flood water sources in Nepal are contaminated at the exact moment that "
                 "backhaul networks are least reliable, so a monitoring design that only publishes when the "
                 "broker is reachable loses its most valuable readings. This paper implements and quantitatively "
                 "evaluates the software and cloud layer of a three-node water-quality fleet. A Python virtual "
                 "ESP32-S3 generator produces coupled pH, turbidity, TDS, temperature and flow telemetry; every "
                 "reading is persisted to SQLite before transmission; and an MQTT/TLS QoS 1 transport replays "
                 "buffered rows with their original acquisition timestamps. Three devices are provisioned in "
                 "ThingsBoard Cloud with alarm rules, a duty-officer dashboard and two-way RPC scenario control. "
                 "A 240 s experiment with a 20 s simulated cellular outage generated 362 readings, all of which "
                 "became Cloud-visible (100% delivery, zero loss). Live edge-acquisition-to-PUBACK latency over "
                 "353 messages had a mean of 196.9 ms, median 194.0 ms, P95 203.4 ms and maximum 629.0 ms. "
                 "Fifteen Cloud alarm events gave a mean activation delay of 544.8 ms. Mean recovery time across "
                 "three nodes was 3302.7 ms at a measured flush rate of 5.50 rows/s. Because the Cloud REST API "
                 "exposes only the device-supplied timestamp, true server-ingestion latency is explicitly "
                 "reported as not measurable rather than estimated.")

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    set_run(p.add_run("Index Terms-Internet of Things, water quality monitoring, edge resilience, "
                      "store-and-forward, SQLite, MQTT, ThingsBoard, telemetry timestamp preservation."),
            size=9, italic=True)

    # ---------------- I. introduction ----------------
    heading(doc, "I. INTRODUCTION")
    body(doc, "Nepal's monsoon floods repeatedly damage water-supply infrastructure and degrade source "
              "quality. The 2021 Melamchi event destroyed headworks serving the Kathmandu valley and deposited "
              "large volumes of sediment in the catchment [1], [2]. Hillside districts such as Rasuwa and "
              "Nuwakot face the same combination of intense rainfall, landslides and interrupted transport "
              "routes. Community water-safety studies in Nepal show that microbial contamination and supply "
              "interruption persist after such events [3]. A duty officer therefore needs continuous, "
              "geographically labelled evidence of which sources remain safe, not occasional laboratory samples.")
    body(doc, "Low-cost IoT systems can provide that evidence, but most published designs assume continuous "
              "connectivity: a Wi-Fi or LoRa node samples sensors and pushes values to a cloud dashboard [4]-[7], "
              "[8]. During a flood, the cellular backhaul and mains power are precisely what fail. A publisher "
              "without a local durable buffer produces a gap in the chart at the moment when turbidity and "
              "sewage ingress peak. The design requirement for this work is therefore not merely telemetry "
              "visualisation but offline resilience with historical backfill.")
    body(doc, "This manuscript documents the implemented software and cloud layer and evaluates it with "
              "measured rather than illustrative numbers. The contributions are: (i) a physically coupled "
              "contamination-event model in which one rainfall envelope drives turbidity, TDS, pH and flow "
              "together; (ii) a write-ahead SQLite store-and-forward path that preserves acquisition time "
              "across an outage and replays in batches at QoS 1; (iii) a three-node ThingsBoard Cloud "
              "deployment with hysteresis-shaped alarm rules, a duty-officer dashboard and RPC scenario "
              "control; and (iv) a reproducible measurement harness that reports latency, delivery, alarm "
              "delay, buffer flush, recovery and loss with explicit measurement boundaries.")
    body(doc, "The rest of the paper is organised as follows. Section II positions the work against related "
              "systems. Section III recapitulates the architecture. Section IV details the implementation. "
              "Section V analyses resources and risks. Section VI presents measured results and limitations, "
              "and Section VII concludes.")

    # ---------------- II. related work ----------------
    heading(doc, "II. RELATED WORK")
    body(doc, "Low-cost water-quality IoT. Several studies integrate ESP32-class microcontrollers with pH, "
              "turbidity, TDS and temperature probes and forward readings to cloud platforms. Obasi and "
              "Ulumefoh [6] demonstrated a ten-sample screening system using analogue conditioning, digital "
              "filtering and a Blynk dashboard, reporting wide variation in rejected samples (turbidity up to "
              "2500 NTU, pH up to 12.34). Ooko et al. [7] used a four-layer sensing/edge/GSM/cloud architecture "
              "in resource-constrained settings and reported deviations of 0.1 pH, 0.3 NTU and 10 ppm TDS. "
              "Sijabat et al. [8] combined pH, TDS and turbidity with LoRa and a Firebase-backed dashboard. "
              "These works establish that multi-parameter screening is affordable, but they treat connectivity "
              "as available and do not evaluate outage backfill.")
    body(doc, "Platform and analytics work. Miller et al. [4] survey the maturity of IoT water-quality "
              "monitoring and note that calibration and validation remain the dominant weakness. "
              "Wiryasaputra et al. [5] add cloud-based prediction on top of potable-water telemetry. Their "
              "focus is classification and forecasting, whereas this work concentrates on the transport "
              "semantics that keep the input series complete during a network partition.")
    body(doc, "Resilience literature. Store-and-forward is a recognised edge reliability pattern: messages are "
              "written durably before transmission and acknowledged only after an application-level ACK, with "
              "temporary network failure distinguished from long-term partition [9]. Operationally, a durable "
              "on-disk queue rather than an in-memory batch is required to survive both outage and restart, and "
              "buffer capacity must be sized against outage duration while drain time is governed by the net "
              "upload rate minus the incoming rate [9]. Replayed samples must carry event time so late data "
              "lands in the correct series position instead of bunching at reconnect. Our implementation follows "
              "these principles explicitly: SQLite is the source of truth, MQTT PUBACK is the acknowledgement "
              "boundary, and the client-stamped payload uses acquisition time in Unix epoch milliseconds.")
    body(doc, "Positioning. Compared with prior systems, this work combines a coupled event model, durable "
              "edge buffering with preserved timestamps, Cloud-native alarm hysteresis, and a measured "
              "evaluation that separates broker confirmation from Cloud ingestion. It deliberately uses a "
              "virtual node rather than hardware, which limits sensor-accuracy claims but makes the outage and "
              "event experiments repeatable and fully instrumentable.")

    # ---------------- III. architecture ----------------
    heading(doc, "III. SYSTEM ARCHITECTURE")
    body(doc, "The architecture follows the fixed project decision of a direct cellular path from a Python "
              "virtual edge node through SQLite and MQTT/TLS to ThingsBoard, with no LoRaWAN gateway and no "
              "Node-RED in the mandatory path. Fig. 1 shows the implemented data flow and the acknowledgement "
              "boundary.")
    figure(doc, arch, "Fig. 1. Implemented edge-to-cloud data path. The durable store sits between generation "
                      "and publish; the client-stamped payload preserves acquisition time on replay.")
    body(doc, "Each virtual node owns a telemetry generator, a SQLite database, an MQTT client and a distinct "
              "device access token, so one node's outage or replay cannot affect the others. Three nodes are "
              "placed at demonstrative post-flood water-source sites in Rasuwa district, listed in Table I. "
              "These are scenario coordinates, not surveyed sensor locations.")
    table(doc,
          ["Node", "Device name", "Area", "Latitude", "Longitude"],
          [["node-01", "JalSanket-Node-01", "Dhunche", "28.1100", "85.2900"],
           ["node-02", "JalSanket-Node-02", "Syafrubesi", "28.0920", "85.3610"],
           ["node-03", "JalSanket-Node-03", "Rasuwagadhi", "28.1710", "85.3870"]],
          "TABLE I\nTHREE INDEPENDENT VIRTUAL NODES AND DEMONSTRATION SITES",
          [0.55, 1.25, 0.75, 0.38, 0.38])
    body(doc, "Telemetry parameters and their nominal ranges follow the assessment brief and are summarised in "
              "Table II. The five measured quantities plus GPS coordinates are packed into a single reading.")
    table(doc,
          ["Key", "Unit", "Baseline", "Event behaviour"],
          [["ph", "-", "6.8-7.6", "depressed non-linearly, floor 6.0"],
           ["turbidity_ntu", "NTU", "2-8", "fast rise to 260"],
           ["tds_ppm", "ppm", "120-250", "rises to 535"],
           ["water_temp_c", "deg C", "16-24", "diurnal cycle, independent"],
           ["flow_lpm", "L/min", "8-18", "surge then dip; 0 if interrupted"],
           ["latitude, longitude", "deg", "site", "static per node"]],
          "TABLE II\nTELEMETRY PARAMETERS AND MODELLED BEHAVIOUR",
          [0.85, 0.42, 0.62, 1.42])
    body(doc, "Two payload forms are used. Live telemetry is sent with the explicit client-stamped form "
              "{\"ts\": acquisition_ms, \"values\": {...}}, which is mandatory for buffered replay because "
              "ThingsBoard otherwise assigns its own arrival time. Replay sends an array of such objects in "
              "chronological batches. A separate client-side attribute publication carries derived node state "
              "such as safety status and device name.")

    # ---------------- IV. implementation ----------------
    heading(doc, "IV. IMPLEMENTATION")

    subheading(doc, "A. Edge simulation logic")
    body(doc, "Normal variation is produced by three latent mean-reverting Ornstein-Uhlenbeck drivers: a "
              "runoff state (time constant 300 s) coupling pH, turbidity and TDS; a flow state (120 s); and a "
              "temperature state (900 s). With sub-stepping for stability, one update is")
    equation(doc, "x[k+1] = x[k] + (-x[k]/tau) h + sigma sqrt(2/tau) N(0,1) sqrt(h),  h = dt/n", 1)
    body(doc, "where dt = sample_interval x time_scale = 2 x 20 = 40 physical seconds per wall-clock tick. "
              "Water temperature adds a diurnal sinusoid centred at 20 deg C with amplitude 4 deg C; each "
              "parameter then receives small Gaussian noise and is clamped to a physical range.")
    body(doc, "A scripted command, trigger_contamination, does not write high values. It records the current "
              "simulation time and activates a two-timescale rainfall/runoff envelope with a 120 s rise "
              "constant and a 2400 s washout constant, normalised so its peak is exactly one:")
    equation(doc, "E(u) = max(0, [exp(-u/2400) - exp(-u/120)] / Emax),  u = t - t_event", 2)
    body(doc, "The single envelope couples all affected parameters. Turbidity and TDS interpolate from their "
              "normal baselines toward 260 NTU and 535 ppm respectively (Eq. 3-4), while pH is suppressed by a "
              "Hill-type inhibition toward a hard floor rather than being arbitrarily lowered (Eq. 5). Flow "
              "receives a short pressure surge followed by a mild sustained reduction (Eq. 6).")
    equation(doc, "turbidity = turb_norm + (260 - turb_norm) E", 3)
    equation(doc, "tds = tds_norm + (535 - tds_norm) E", 4)
    equation(doc, "pH = 6.0 + (pH_norm - 6.0) / (1 + (E/0.35)^1.5)", 5)
    equation(doc, "flow = flow_norm + 4(u/40)exp(1-u/40) - 2.5E", 6)
    body(doc, "A separate command, set_supply_interrupted, overrides flow to exactly zero; reset restores the "
              "seeded state so the scenario is repeatable. With 20x time compression the contamination rise "
              "takes roughly six wall seconds and the washout about two wall minutes, which is suitable for a "
              "live demonstration. Listing 1 shows the essential structure of the generator tick.")
    listing(doc, [
        "def tick(self, at=None):",
        "    dt = cfg.sample_interval_s * cfg.time_scale",
        "    self._sim_time_s += dt",
        "    self._runoff = ou(self._runoff, 300, 0.55, dt)",
        "    turb_norm = clamp(5.0 + 1.1*self._runoff + noise(0.25), 2, 8)",
        "    E = self._contamination_envelope()          # 0 -> 1 -> 0",
        "    turbidity = turb_norm + (260 - turb_norm) * E",
        "    tds       = tds_norm  + (535 - tds_norm)  * E",
        "    ph = 6.0 + (ph_norm - 6.0) / (1 + (E/0.35)**1.5)",
        "    return Reading(..., acquisition_ms=acquired_at, ...)",
    ], "Listing 1. Coupled contamination model (abridged from jalsanket/telemetry.py).")
    body(doc, "The complete parameter model is defined by a single configuration dataclass so that the physics "
              "is auditable in one place. Table III lists the coefficients used in the reported experiment. "
              "Each baseline and range follows the assessment brief; the event coefficients were chosen to make "
              "the physical story legible rather than to maximise a score.")
    table(doc,
          ["Parameter / mechanism", "Coefficient", "Value", "Justification"],
          [["Normal runoff state", "tau_runoff", "300 s", "shared weather signal, slow"],
           ["Turbidity coupling", "k_turb", "1.1 NTU", "silt raises scatter"],
           ["pH inhibition", "k, n, floor", "0.35, 1.5, 6.0", "non-linear, bounded"],
           ["TDS event peak", "peak_TDS", "535 ppm", "dissolved load with ingress"],
           ["Turbidity event peak", "peak_NTU", "260 NTU", "within 100-800 event band"],
           ["Rise / washout", "tau_r, tau_d", "120 s, 2400 s", "fast rise, slow decay"],
           ["Pressure transient", "amp, tau", "4 L/min, 40 s", "brief breach surge"],
           ["Flow reduction", "amp", "2.5 L/min", "sustained mild dip"],
           ["Diurnal temperature", "mean, amp", "20, 4 deg C", "16-24 deg C band"],
           ["Clock compression", "time_scale", "20", "physics unchanged"]],
          "TABLE III\nPARAMETER MODEL COEFFICIENTS USED IN THE EXPERIMENT",
          [1.15, 0.72, 0.68, 0.75])
    body(doc, "TDS coupling. The dissolved-solids rise is tied to the same runoff envelope as turbidity rather "
              "than to an independent random walk. This represents dissolved salts and organic load arriving with "
              "the silt-laden inflow. A linear interpolation from the 185 ppm baseline toward a 535 ppm peak was "
              "selected because it crosses the 500 ppm Critical threshold near the top of the event, giving the "
              "alarm a clear and explainable trigger. Using an independent generator would break the causal story "
              "the brief explicitly asks for: a silt event must move turbidity, TDS and pH together.")
    body(doc, "pH coupling. A linear depression would risk physically implausible values during a long event. The "
              "model therefore uses a Hill-type inhibition with half-effect at E = 0.35 and exponent 1.5, plus a "
              "hard floor of 6.0. The response is steep early, then saturates: organic acid production cannot "
              "continue lowering pH indefinitely. This satisfies the brief's requirement that pH coupling be "
              "non-linear with a physically sensible floor, and it keeps the 'pH Out of Range Critical' alarm "
              "(pH < 6.5) reachable without pushing the reading below any credible drinking-water value.")
    body(doc, "Flow coupling. The flow channel carries three superimposed effects: a mean-reverting baseline state "
              "(tau = 120 s), a short positive pressure transient at the breach, and a mild sustained reduction "
              "proportional to the event envelope. The transient uses the form (u/40) exp(1-u/40), which peaks at "
              "u = 40 physical seconds and then decays, modelling a pressure pulse that dissipates as the network "
              "settles. Supply interruption is a fourth, overriding case that sets flow to exactly zero and is used "
              "to exercise the separate Maintenance alarm.")

    subheading(doc, "B. Store-and-forward design")
    body(doc, "The SQLite schema stores each acquisition with acquisition_ms, stored_at_ms, synced and "
              "synced_at_ms, plus the five parameters, coordinates and loss accounting. Write-ahead logging "
              "[10] is enabled so a reader or a crash cannot block the write path. The mandatory ordering is "
              "generate -> persist -> attempt publish, enforced in VirtualEdgeNode.tick(); a publish failure "
              "never discards the row. On PUBACK the row is marked synced, and only unsynced rows are eligible "
              "for replay.")
    listing(doc, [
        "reading = generator.tick()                 # 1. acquire",
        "row_id  = store.persist(reading)            # 2. durable, synced=0",
        "if transport.connected:",
        "    transport.publish_live(reading, row_id) # 3. QoS 1 publish",
        "    # on_publish -> store.mark_synced(row_ids)",
        "else:",
        "    transport.needs_replay = True           # buffer grows, no crash",
        "# on reconnect:",
        "for batch in store.unsynced_batches(size=20):",
        "    publish(json.dumps([stamped(r) for r in batch]), is_replay=True)",
    ], "Listing 2. Sync algorithm and replay loop (abridged).")
    body(doc, "The database schema separates measurement time from simulator time. acquisition_ms is the reading's "
              "acquisition instant in Unix epoch milliseconds and is the value that must survive replay. "
              "stored_at_ms and synced_at_ms are real-clock anchors used only for local latency accounting. The "
              "generator's compressed simulation clock is deliberately not persisted, so it can never be confused "
              "with a measurement timestamp. Two covering indexes order unsynced rows by acquisition time, both "
              "globally and per node, which makes chronological batch retrieval efficient even after a long outage.")
    listing(doc, [
        "CREATE TABLE readings (",
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,",
        "  node_id TEXT NOT NULL, acquisition_ms INTEGER NOT NULL,",
        "  acquired_at TEXT NOT NULL,",
        "  ph REAL, turbidity_ntu REAL, tds_ppm REAL,",
        "  water_temp_c REAL, flow_lpm REAL,",
        "  latitude REAL NOT NULL, longitude REAL NOT NULL,",
        "  synced INTEGER NOT NULL DEFAULT 0 CHECK (synced IN (0,1)),",
        "  stored_at_ms INTEGER NOT NULL, synced_at_ms INTEGER,",
        "  publish_attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);",
        "CREATE INDEX idx_readings_unsynced_order",
        "  ON readings (synced, acquisition_ms, id);",
        "CREATE INDEX idx_readings_node_unsynced_order",
        "  ON readings (node_id, synced, acquisition_ms, id);",
        "CREATE TABLE loss_events (id INTEGER PRIMARY KEY AUTOINCREMENT,",
        "  occurred_at_ms INTEGER NOT NULL, node_id TEXT NOT NULL,",
        "  reason TEXT NOT NULL, acquisition_ms INTEGER NOT NULL, detail TEXT);",
    ], "Listing 3. SQLite schema (abridged from jalsanket/storage.py).")
    body(doc, "Write-ahead logging is enabled with synchronous=FULL, giving fsync-level durability on each commit. "
              "The cost is extra I/O per reading, but at one row every two seconds it is negligible and it makes "
              "the claim that SQLite is the source of truth defensible: a crash after generate but before publish "
              "still leaves a replayable row. On successful QoS 1 PUBACK the corresponding row ids are marked "
              "synced in one transaction; publish_attempts and last_error record failures for diagnosis.")
    body(doc, "The buffer is bounded at 10800 rows, equivalent to six hours at one reading every two seconds, "
              "and its eviction policy is drop-newest: when full, new readings are rejected and a loss event is "
              "recorded rather than overwriting the beginning of the outage. For an audit-style water-safety "
              "record, the complete early sequence is more valuable than the tail, and a visible loss counter "
              "makes the trade-off explicit. Connection handling uses exponential backoff from 2 s to 60 s: a "
              "short minimum avoids slow recovery from transient cellular flaps, while a one-minute ceiling "
              "avoids the power and signalling cost of perpetual rapid reconnection attempts. Logs distinguish "
              "authentication failure from network failure and report state transitions, buffer depth and "
              "rows flushed.")
    body(doc, "Timestamp preservation is verified by matching Cloud timeseries keys (device, device-supplied "
              "ts) against local acquisition_ms. In the measured run all 362 generated rows matched, confirming "
              "that replayed samples remain in their original historical position rather than being "
              "re-stamped at reconnect.")

    subheading(doc, "C. Cloud configuration")
    body(doc, "A device profile named for the water-quality node was created with MQTT transport settings, the "
              "seven telemetry keys and a 60000 ms SERVER_SCOPE inactivity timeout. Three devices were "
              "provisioned with distinct access tokens; tokens are supplied only through environment variables "
              "or a git-ignored .env file and never appear in evidence or logs [11]. Six Alarm Rules 2.0 "
              "definitions implement the required thresholds with the specified hysteresis gap, which prevents "
              "a node oscillating at exactly 50 NTU from generating hundreds of alarm transitions.")
    table(doc,
          ["Alarm", "Create", "Clear"],
          [["High Turbidity Warning", "turbidity > 50", "turbidity < 40"],
           ["Gross Contamination Critical", "turbidity > 200", "turbidity < 150"],
           ["pH Out of Range Critical", "pH < 6.5 or > 8.5", "6.7 <= pH <= 8.3"],
           ["High TDS Critical", "TDS > 500", "TDS < 450"],
           ["Supply Interruption Major", "flow == 0 sustained", "flow > 0"],
           ["Node Inactive Critical", "inactivity timeout", "telemetry resumes"]],
          "TABLE IV\nCLOUD ALARM RULES WITH HYSTERESIS",
          [1.35, 0.95, 1.00])
    body(doc, "The duty-officer dashboard was organised around a single operational question - which source is "
              "unsafe right now? A fleet-health table and a colour-coded map answer it first; gauges and "
              "time-series charts provide detail; an alarms table supplies severity and duration. Every widget "
              "is bound to one fleet alias so measurements remain labelled by source name.")
    table(doc,
          ["Widget", "Bound data", "Operational purpose"],
          [["Fleet health / summary", "status", "unsafe source at a glance"],
           ["pH, turbidity, TDS gauges", "three keys", "banded against thresholds"],
           ["Multi-parameter chart", "turbidity, pH, TDS", "event shape and backfilled gap"],
           ["Temp & flow chart", "water_temp_c, flow_lpm", "supply continuity"],
           ["OpenStreetMap", "lat, lon, status", "three Rasuwa sites, severity colour"],
           ["Alarms table", "active/cleared", "severity and duration"]],
          "TABLE V\nDUTY-OFFICER DASHBOARD COMPOSITION",
          [1.10, 0.92, 1.28])
    body(doc, "Scenario control uses ThingsBoard two-way RPC. The node subscribes to "
              "v1/devices/me/rpc/request/+ and accepts trigger_contamination, set_supply_interrupted and reset, "
              "replying on the response topic. Because ThingsBoard permits a single MQTT session per access "
              "token, scenario commands were sent through Cloud REST while the fleet was connected over MQTT; "
              "a second raw MQTT client with the same token would take over the session and disconnect the "
              "fleet. This choice is documented as a risk mitigation in Section V.")
    listing(doc, [
        "# server -> device, topic v1/devices/me/rpc/request/<id>",
        '{"method": "trigger_contamination", "params": {}}',
        "# device -> server, topic v1/devices/me/rpc/response/<id>",
        '{"ok": true, "method": "trigger_contamination"}',
        "# supply interruption",
        '{"method": "set_supply_interrupted", "params": {"interrupted": true}}',
        "# restore seeded normal state",
        '{"method": "reset", "params": {}}',
    ], "Listing 4. Two-way RPC request and response payloads.")
    body(doc, "Alarm activation uses Cloud Alarm Rules 2.0. Four threshold rules evaluate a simple expression on "
              "incoming telemetry; Supply Interruption adds a DURATION condition requiring flow_lpm to remain at "
              "zero for 30 s before activation, and Node Inactive uses the 60000 ms SERVER_SCOPE inactivity "
              "timeout. Each rule stores explicit create and clear expressions so the hysteresis gap is enforced "
              "on the Cloud side rather than in the edge script. This matters for traceability: the alarm state a "
              "duty officer sees is produced by the platform configuration, not by a convenience flag in the "
              "simulator.")

    # ---------------- V. resource and risk ----------------
    heading(doc, "V. RESOURCE AND RISK ANALYSIS")

    subheading(doc, "A. Tool justification")
    body(doc, "Python 3.10+ was appropriate for a virtual ESP32-S3 because it offers readable physical models, "
              "fast iteration and direct access to the standard-library sqlite3 module and the paho-mqtt client "
              "[12]. SQLite provides an embedded, transactional, crash-resistant store with write-ahead "
              "logging and no separate server, which is exactly the durability boundary required here [10]. "
              "MQTT was selected for its lightweight publish/subscribe model, QoS 1 acknowledgement and "
              "wide Cloud support [13]. ThingsBoard Cloud supplies device provisioning, alarm rules, a map "
              "widget and REST APIs without operating a local broker. A production ESP32-S3 firmware would "
              "replace Python with C/C++ or MicroPython, use NTP or RTC synchronisation to bound clock drift, "
              "store readings in flash with wear levelling, add a GSM/Cellular modem with power-aware "
              "reconnection, and require secure certificate provisioning and over-the-air update support.")
    body(doc, "The buffer sizing follows a simple capacity calculation: the incoming rate is one row every two "
              "seconds, a 10800-row buffer covers six hours of outage, and the observed replay rate of about "
              "5.5 rows/s exceeds the incoming rate fivefold, so the backlog drains quickly. Alarm thresholds "
              "and hysteresis follow the brief rather than being tuned to the demo, preserving traceability "
              "between Task 2 design and Task 3 implementation.")

    subheading(doc, "B. Risk mitigation")
    body(doc, "Connection handling. Early tests showed that assigning paho callback attributes on the "
              "transport wrapper did not fire because the client had already bound its callbacks; the collector "
              "therefore rebinds the client's on_publish and on_connect handlers in-process. A separate risk "
              "was duplicate MQTT sessions with the same device token, which ThingsBoard resolves by "
              "disconnecting the previous session. All scenario commands were consequently delivered through "
              "REST RPC while the fleet was live.")
    body(doc, "Timestamp semantics and payload formatting. ThingsBoard accepts both server-stamped and "
              "client-stamped payloads. Using the server-stamped form would silently destroy the outage "
              "timeline, so the implementation always includes ts in Unix epoch milliseconds. The Cloud REST "
              "timeseries endpoint returns only that device-supplied ts and no server ingestion timestamp; "
              "reporting an end-to-end Cloud latency from it would be fabricated. The evaluation therefore "
              "reports edge acquisition to QoS 1 PUBACK as a clearly labelled broker-confirmation metric and "
              "states Cloud ingestion latency as not measurable.")
    body(doc, "Alarm flapping. Create and clear thresholds are separated by a hysteresis band so a signal "
              "hovering at a boundary does not toggle continuously. For duration-based rules such as Supply "
              "Interruption, the reported activation delay also contains the sustained-condition window and "
              "is therefore interpreted per alarm type.")
    body(doc, "Clock drift and correlation. Acquisition timestamps use the host UTC clock; a real deployment "
              "would require NTP. While correlating evidence, an initial implementation keyed PUBACK callbacks "
              "by SQLite row id alone and produced negative latencies, because row ids are unique per node "
              "database, not globally. Keying by (node_id, row_id) resolved the collision, and a deterministic "
              "regression test now prevents recurrence.")
    body(doc, "Table VI summarises the principal engineering risks and the concrete mitigation applied to each. "
              "The list is drawn from problems actually encountered while building and verifying the system, not "
              "from a generic checklist.")
    table(doc,
          ["Risk", "Consequence if unhandled", "Mitigation implemented"],
          [["Duplicate MQTT token session", "Fleet silently disconnected (CONNACK 128)",
            "REST RPC for scenarios; one session per token"],
           ["Server-stamped replay", "Outage gap collapsed to reconnect time",
            "Explicit ts in ms on every payload"],
           ["Row-id collision across nodes", "Negative or wrong latency attribution",
            "Key PUBACK by (node_id, row_id)"],
           ["Alarm flapping at threshold", "Hundreds of spurious transitions",
            "Hysteresis create/clear bands"],
           ["Unbounded buffer growth", "Memory/disk exhaustion in long outage",
            "10800-row cap, drop-newest, loss_events"],
           ["TLS / auth error misread as network", "Wasted reconnect loops",
            "Separate auth and network log states"],
           ["Unverified coordinate source", "Map markers drift from config",
            "Coordinates generated from fleet.py"]],
          "TABLE VI\nENGINEERING RISKS AND MITIGATIONS",
          [1.05, 1.05, 1.20])

    # ---------------- VI. results ----------------
    heading(doc, "VI. RESULTS AND DISCUSSION")
    body(doc, "The evaluation used a single 240 s run of the three-node fleet against ThingsBoard Cloud with "
              "one normal 20 s simulated cellular outage (tick 40 to 50). Contamination commands were issued at "
              "ticks 4, 6 and 8, reset at 28, supply interruption at ticks 60, 62 and 64, and cleared at 90. "
              "These are existing generator/RPC controls; no telemetry value was injected artificially. Four "
              "independent evidence sources were correlated: SQLite rows, instrumented PUBACK and CONNACK "
              "events, Cloud timeseries REST responses, and Cloud alarm records.")
    body(doc, "The scripted timeline in Table VII keeps the demonstration repeatable and every event attributable. "
              "Ticks are wall-clock sample intervals of two seconds; the simulator clock advances forty physical "
              "seconds per tick. Scenario events are delivered as RPC commands to individual devices, so each node "
              "can be treated separately and the cross-node chart shows the staggered onset.")
    table(doc,
          ["Tick", "Wall time (s)", "Command / event", "Physical time (s)"],
          [["4, 6, 8", "8, 12, 16", "trigger_contamination, nodes 01-03", "160, 240, 320"],
           ["28", "56", "reset, all nodes", "1120"],
           ["40-50", "80-100", "simulated cellular outage, 20 s", "1600-2000"],
           ["60, 62, 64", "120, 124, 128", "set_supply_interrupted(True)", "2400, 2480, 2560"],
           ["90", "180", "set_supply_interrupted(False)", "3600"]],
          "TABLE VII\nSCRIPTED SCENARIO TIMELINE FOR THE MEASURED RUN",
          [0.55, 0.85, 1.35, 0.85])

    subheading(doc, "A. Data visualisation")
    figure(doc, ROOT / "evidence" / "dashboard_cloud.png",
           "Fig. 2. Duty-officer dashboard during normal operation. Fleet health and the Rasuwa map answer the "
           "safety question first; gauges and charts provide detail.")
    figure(doc, ROOT / "evidence" / "dashboard_cloud_alarms.png",
           "Fig. 3. Alarm evidence. Active and cleared alarms appear with severity and timing; the affected "
           "source is reflected in the fleet table.")
    body(doc, "The dashboard screenshots demonstrate normal operation and the contamination response. Because "
              "all three nodes publish latitude and longitude as telemetry, the map markers follow the "
              "source-of-truth coordinates defined in the fleet configuration rather than manual Cloud edits.")

    subheading(doc, "B. Alerting evidence")
    body(doc, "Fifteen Cloud alarm events were captured, three per node across five threshold-based types "
              "(Table VIII). The delays for the four contamination-related types range from 134 ms to 220 ms and "
              "reflect rule evaluation after the triggering telemetry. Supply Interruption delays of about "
              "2000 ms are longer because that rule requires a sustained zero-flow condition before it "
              "activates, rather than firing on a single reading. "
              "The mean over all fifteen events is 544.8 ms and the median is 189.0 ms, so the mean should be "
              "read together with the per-type breakdown rather than as a single rule latency. A Node Inactive "
              "alarm is configured through the profile inactivity timeout but did not activate in this run, "
              "because reconnection with backoff kept every node within the timeout window.")
    table(doc,
          ["Alarm type", "Count", "Delays (ms)"],
          [["Gross Contamination Critical", "3", "188, 211, 141"],
           ["High TDS Critical", "3", "220, 161, 173"],
           ["High Turbidity Warning", "3", "216, 134, 159"],
           ["pH Out of Range Critical", "3", "147, 208, 189"],
           ["Supply Interruption Major", "3", "2008, 2004, 2013"]],
          "TABLE VIII\nCLOUD ALARM EVENTS BY TYPE IN THE MEASURED RUN",
          [1.45, 0.42, 1.43])

    subheading(doc, "C. Resilience evidence")
    figure(doc, ROOT / "evidence" / "metrics" / "buffer_depth_timeline.png",
           "Fig. 4. Buffer depth over the experiment. Depth rises only during the simulated outage and returns "
           "to zero after replay.")
    body(doc, "Each node buffered two readings during the outage and replayed them automatically. Recovery was "
              "anchored at the actual link-drop time rather than the scripted restore tick, because the "
              "transport reconnects with backoff, often before the demonstration restore command. Table IX "
              "reports the per-node decomposition into reconnect delay and flush time.")
    table(doc,
          ["Node", "Recovery (ms)", "Reconnect (ms)", "Rows", "Flush (rows/s)"],
          [["node-01", "3529", "3165", "2", "5.51"],
           ["node-02", "3176", "2808", "2", "5.45"],
           ["node-03", "3203", "2843", "2", "5.56"]],
          "TABLE IX\nPER-NODE RECOVERY AND BUFFER FLUSH",
          [0.62, 0.72, 0.72, 0.40, 0.84])
    body(doc, "The Cloud timeseries contained all 362 acquisition timestamps after full sync, including the "
              "rows replayed after the outage, confirming chronological backfill of the gap. The SQLite "
              "loss_events table recorded zero evictions; no capacity exhaustion was exercised because the "
              "outage was short by design.")

    subheading(doc, "D. Performance measurement")
    figure(doc, ROOT / "evidence" / "metrics" / "latency_distribution.png",
           "Fig. 5. Distribution of edge-acquisition-to-PUBACK latency for live messages (n = 353).")
    body(doc, "Metric definitions and boundaries are made explicit in Table X. Where a quantity cannot be "
              "measured honestly, the table says so instead of supplying an estimate.")
    table(doc,
          ["Metric", "Start", "End / note"],
          [["Edge-to-PUBACK latency", "SQLite acquisition_ms", "PUBACK callback; broker only"],
           ["Cloud ingestion latency", "-", "Not measurable; no server timestamp"],
           ["Delivery ratio", "generated rows", "Cloud key (device, acquisition_ms)"],
           ["Alarm delay", "alarm startTs", "alarm createdTime"],
           ["Flush throughput", "first replay publish", "last replay PUBACK"],
           ["Recovery time", "outage onset", "buffer empty"],
           ["Data loss", "loss_events", "drop-newest evictions only"]],
          "TABLE X\nMETRIC DEFINITIONS AND MEASUREMENT BOUNDARIES",
          [1.05, 0.85, 1.40])
    table(doc,
          ["Metric", "Measured value"],
          [["Messages generated / Cloud-visible / lost", "362 / 362 (100%) / 0 (0%)"],
           ["Live edge-to-PUBACK latency (n=353)",
            "mean 196.9 ms; median 194.0 ms; P95 203.4 ms; max 629.0 ms"],
           ["Replay edge-to-PUBACK latency (n=9)",
            "mean 1640.6 ms; median 1118.0 ms; max 3532.0 ms"],
           ["Alarm activation delay (n=15)",
            "mean 544.8 ms; median 189.0 ms; P95 2009.5 ms"],
           ["Recovery time (n=3)", "mean 3302.7 ms; median 3203.0 ms"],
           ["Buffer flush throughput (n=3)", "mean 5.50 rows/s; median 5.51 rows/s"],
           ["Still buffered at end", "0 rows"],
           ["Cloud ingestion latency", "not reported - not measurable"]],
          "TABLE XI\nMEASURED RESULTS FROM THE 240 s EXPERIMENT",
          [1.45, 1.85])
    body(doc, "The live latency distribution is tight, with P95 only about 9 ms above the median and a single "
              "629 ms outlier. Replay latency is an order of magnitude larger because it includes batching "
              "and backoff, which is expected and is reported separately. Delivery reached 100% including the "
              "outage window, so the store-and-forward path did not trade timeliness for completeness.")

    subheading(doc, "E. Limitations")
    body(doc, "First, QoS 1 PUBACK confirms broker receipt, not dashboard or Cloud ingestion; with no Cloud "
              "ingestion timestamp exposed, true end-to-end Cloud latency cannot be quantified. Second, the "
              "sensor readings are surrogate indicators from a software model, not calibrated measurements, "
              "and sensor accuracy is unvalidated. Third, the simulation-versus-hardware gap means power "
              "consumption, radio behaviour and flash wear are not represented. Fourth, the outage was a normal "
              "20 s scenario with only two buffered rows per node, so buffer capacity exhaustion was not "
              "measured. Fifth, results come from one controlled run on a shared Cloud tenant, so network and "
              "tenant load affect the latency figures. Finally, the Rasuwa coordinates are demonstration "
              "positions, not surveyed installation sites.")

    # ---------------- VII. conclusion ----------------
    heading(doc, "VII. CONCLUSION AND FUTURE WORK")
    body(doc, "This work implemented and measured a three-node virtual water-quality fleet with durable edge "
              "buffering and ThingsBoard Cloud visualisation. The system generated 362 readings during a "
              "240 s experiment containing a 20 s cellular outage, delivered all of them to the Cloud with "
              "original timestamps, produced fifteen alarm events with a mean activation delay of 544.8 ms, "
              "and drained each buffer in roughly 3.2-3.5 s at about 5.5 rows/s. Zero data loss was observed. "
              "The results support the central design claim: persisting before publishing makes the readings "
              "from the outage available to the duty officer instead of leaving a gap in the chart.")
    body(doc, "Future work will add a sustained capacity-exhaustion test, multi-run latency statistics across "
              "different network conditions, an NTP-bound clock discipline study, and a server-side WQI rule "
              "with critical-alarm notification. Mapping the RPC scenario controls to dashboard buttons would "
              "also make the live demonstration more direct, and replacing the Python virtual node with an "
              "ESP32-S3 prototype would allow the sensor-accuracy and power claims left open here to be "
              "evaluated.")

    # ---------------- references ----------------
    # ---------------- VIII. reproducibility ----------------
    heading(doc, "VIII. REPRODUCIBILITY AND EVIDENCE")
    body(doc, "All reported numbers are reproducible from the submitted source and the evidence manifest. The "
              "verification suite is deterministic: the telemetry generator uses fixed per-node seeds (42, 43 and "
              "44), and the offline tests inject explicit acquisition timestamps so no result depends on wall-clock "
              "timing. The live experiment uses the project's own scenario controls and writes raw evidence to "
              "evidence/metrics/ before any derived metric is calculated.")
    listing(doc, [
        ".venv/bin/python -m compileall -q jalsanket",
        ".venv/bin/python verify_phase1.py   # generator and coupling",
        ".venv/bin/python verify_phase2.py   # SQLite buffer and replay",
        ".venv/bin/python verify_phase3.py   # MQTT/TLS transport",
        ".venv/bin/python verify_phase4.py   # ThingsBoard config and alarms",
        ".venv/bin/python verify_metrics.py  # metric calculations",
        ".venv/bin/python run_fleet.py --duration 240",
        ".venv/bin/python collect_metrics.py # orchestrates the scenario run",
    ], "Listing 5. Commands used for verification and the measured experiment.")
    table(doc,
          ["Evidence file", "What it establishes"],
          [["metrics_results.json", "All calculated statistics in this paper"],
           ["raw_db_rows.csv", "Generated rows and acquisition timestamps"],
           ["raw_latency_samples.csv", "PUBACK correlation, live and replay"],
           ["raw_cloud_alarms.csv", "Cloud startTs, createdTime, delay"],
           ["raw_link_and_connect_events.csv", "Link drop and CONNACK events"],
           ["raw_recovery_events.csv", "Reconnect and buffer-empty anchors"],
           ["raw_loss_events.csv", "Eviction accounting (zero here)"],
           ["manifest.json", "16 evidence files, secret scan findings empty"]],
          "TABLE XII\nPRINCIPAL EVIDENCE FILES UNDER evidence/metrics/",
          [1.45, 1.85])
    body(doc, "The manifest records a clean secret scan and the JWT fingerprint rather than the token itself. "
              "Access tokens were supplied only through environment variables and a git-ignored .env file. "
              "Historical evidence files that predate the coordinate correction are retained and explicitly "
              "labelled as earlier snapshots; the live cloud verification JSON and the metrics rerun are the "
              "authoritative sources for the current configuration.")

    heading(doc, "REFERENCES")
    refs = [
        'World Bank, "Melamchi flood disaster in Nepal," Washington, DC, USA, Tech. Rep., 2022.',
        'Asian Development Bank, "Mapping hazards in Nepal\'s Melamchi River: Catchment to enhance Kathmandu\'s water security," Manila, Philippines, 2023.',
        'C. B. Bänziger, A. Schertenleib, B. M. Kunwar, M. R. Bhatta, and S. J. Marks, "Assessing microbial water quality, users\' perceptions and system functionality following a combined water safety intervention in rural Nepal," Front. Water, vol. 3, 2022, doi: 10.3389/frwa.2021.750802.',
        'M. Miller, A. Kisiel, D. Cembrowska-Lech, I. Durlik, and T. Miller, "IoT in water quality monitoring - Are we really here?," Sensors, vol. 23, no. 2, art. 960, 2023, doi: 10.3390/s23020960.',
        'E. T. Wiryasaputra, C.-Y. Huang, Y.-J. Lin, and C.-T. Yang, "An IoT real-time potable water quality monitoring and prediction model based on cloud computing architecture," Sensors, vol. 24, no. 4, art. 1180, 2024, doi: 10.3390/s24041180.',
        'C. Obasi and R. Ulumefoh, "Development of a low-cost IoT-enabled water quality monitoring system using ESP32," Int. J. Sci. Res. Comput. Sci. Eng., vol. 14, no. 5, pp. 58-66, 2026.',
        'S. O. Ooko, L. Cheptegei, and S. M. Karume, "Design and implementation of a low-cost IoT model for real-time water quality monitoring in resource-constrained environments," MUST J. Res. Dev., vol. 7, no. 3, 2026.',
        'A. V. O. Sijabat, A. Hanif, and Irwansyah, "Design and development of an IoT-based river water parameter monitoring system using pH, TDS, and turbidity sensors," J. Artif. Intell. Eng. Appl., vol. 6, no. 1, 2026, doi: 10.59934/jaiea.v6i1.2881.',
        'J. A. Matias and R. J. de A. Macedo, "Resilient IIoT communication via edge-based store-and-forward and SLO monitoring," in Proc. XXVII Workshop Testes e Tolerancia a Falhas (WTF) do SBRC, 2026.',
        'SQLite, "Write-ahead logging," [Online]. Available: https://www.sqlite.org/wal.html',
        'ThingsBoard, "ThingsBoard documentation," [Online]. Available: https://thingsboard.io/docs/',
        'Eclipse Foundation, "Eclipse Paho MQTT Python client," [Online]. Available: https://www.eclipse.org/paho/clients/python/',
        'OASIS Standard, "MQTT version 3.1.1," 2014. [Online]. Available: https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/mqtt-v3.1.1.html',
    ]
    for i, ref in enumerate(refs, 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.18)
        p.paragraph_format.first_line_indent = Inches(-0.18)
        p.paragraph_format.space_after = Pt(2)
        set_run(p.add_run("[" + str(i) + "] " + ref), size=8.5)

    doc.save(DOCX)
    print("Wrote", DOCX)


if __name__ == "__main__":
    build()
