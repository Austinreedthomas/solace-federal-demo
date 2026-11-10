"""Deck generator.

Slides 3, 6, and 7 are drawn in this file. Slides 1, 2, 4, 5, and 8–10
use the tracked deck/slide-NN.svg files. Titles and speaker notes for
those slides are in notes/preserved-notes.json next to start.html (the
parent of deck/).
Run: python3 deck/build_deck.py
"""
from pathlib import Path
from html import escape
import json, re, sys

W = Path(__file__).resolve().parent.parent
import cairosvg
from pypdf import PdfWriter, PdfReader
from pypdf.annotations import Link
import xml.etree.ElementTree as ET

D = W / 'deck'

navy = '#102E43'
teal = '#087F83'
aqua = '#8FE3DA'
muted = '#526A78'
pale = '#EDF6F5'
line = '#B4C9CC'
panel = '#193F53'
white = '#FFFFFF'
soft = '#F3F6F8'
deny = '#9A3B2E'


def text(x, y, lines, size=30, color=navy, weight='normal', leading=1.2, anchor=None):
    if isinstance(lines, str):
        lines = [lines]
    anc = f' text-anchor="{anchor}"' if anchor else ''
    return (f'<text x="{x}" y="{y}" fill="{color}" font-family="Liberation Sans" font-size="{size}" '
            f'font-weight="{weight}"{anc}>'
            + ''.join(f'<tspan x="{x}" dy="{0 if i == 0 else round(size * leading, 1)}">{escape(t)}</tspan>'
                      for i, t in enumerate(lines))
            + '</text>')


def rect(x, y, w, h, fill, stroke='none', r=0, dash=''):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="2" stroke-dasharray="{dash}"/>')


def path(d, c, width=3, dash='', end=False, start=False, nav=False, join='', cap=''):
    m = ''
    if end == 'deny':
        m += ' marker-end="url(#DENY)"'
    elif end:
        m += ' marker-end="url(#NARROW)"' if nav else ' marker-end="url(#ARROW)"'
    if start:
        m += ' marker-start="url(#ARROW)"'
    if join:
        m += f' stroke-linejoin="{join}"'
    if cap:
        m += f' stroke-linecap="{cap}"'
    return f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{width}" stroke-dasharray="{dash}"{m}/>'


def circle(cx, cy, r, fill, stroke='none'):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'


def svg(n, content, title, accent=teal):
    mid = f'deck-arrow-{n}'
    content = (content.replace('url(#ARROW)', f'url(#{mid})').replace('url(#NARROW)', f'url(#{mid}-n)').replace('url(#DENY)', f'url(#{mid}-d)'))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900" '
            f'role="img" aria-label="{escape(title)}"><title>{escape(title)}</title>'
            f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="{accent}"/></marker>'
            f'<marker id="{mid}-n" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="{navy}"/></marker>'
            f'<marker id="{mid}-d" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="{deny}"/></marker></defs>'
            f'{rect(0, 0, 1600, 900, white)}{content}</svg>')


def head(kicker, title, sub):
    return (text(80, 91, kicker, 22, teal, 'bold')
            + text(80, 160, title, 46, navy, 'bold')
            + text(80, 219, sub, 26, muted))


def foot(n, note=''):
    out = path('M80 819H1520', muted, 1)
    if note:
        out += text(80, 856, note, 22, muted)
    return out + text(1468, 856, f'{n:02}', 22, muted)


def ico_satellite(x, y, scale=1.0, fill=navy, label='Satellite'):
    s = scale
    parts = []
    parts.append(rect(x + 38 * s, y + 28 * s, 54 * s, 36 * s, fill, r=4))
    parts.append(rect(x + 4 * s, y + 36 * s, 30 * s, 20 * s, white, fill, r=2))
    parts.append(rect(x + 96 * s, y + 36 * s, 30 * s, 20 * s, white, fill, r=2))
    parts.append(path(f'M{x + 65 * s} {y + 28 * s}V{y + 14 * s}', fill, 3))
    parts.append(circle(x + 65 * s, y + 10 * s, 6 * s, teal))
    parts.append(text(x + 65 * s, y + 92 * s, label, 20, muted, anchor='middle'))
    return ''.join(parts)


def ico_antenna(x, y, scale=1.0, fill=navy, label='Ground link'):
    s = scale
    parts = []
    parts.append(path(f'M{x + 50 * s} {y + 78 * s}V{y + 30 * s}', fill, 3))
    parts.append(path(f'M{x + 50 * s} {y + 30 * s} L{x + 18 * s} {y + 58 * s} L{x + 82 * s} {y + 58 * s} Z', fill, 3))
    parts.append(path(f'M{x + 20 * s} {y + 78 * s}H{x + 80 * s}', fill, 3))
    parts.append(circle(x + 50 * s, y + 22 * s, 5 * s, teal))
    parts.append(path(f'M{x + 28 * s} {y + 18 * s} Q{x + 50 * s} {y + 2 * s} {x + 72 * s} {y + 18 * s}', teal, 2, '4 4'))
    parts.append(text(x + 50 * s, y + 102 * s, label, 20, muted, anchor='middle'))
    return ''.join(parts)


def ico_person(x, y, label='Operator', scale=1.0, fill=navy, ok=None):
    s = scale
    parts = []
    parts.append(circle(x + 40 * s, y + 22 * s, 14 * s, fill))
    parts.append(path(f'M{x + 16 * s} {y + 70 * s} Q{x + 40 * s} {y + 40 * s} {x + 64 * s} {y + 70 * s}', fill, 8))
    parts.append(text(x + 40 * s, y + 96 * s, label, 20, muted, anchor='middle'))
    if ok is True:
        cx, cy = x + 68 * s, y + 18 * s
        parts.append(circle(cx, cy, 14 * s, '#D9F2EF', teal))
        parts.append(path(f'M{cx - 6 * s} {cy} L{cx - 2 * s} {cy + 5 * s} L{cx + 7 * s} {cy - 5 * s}', teal, 3))
    if ok is False:
        cx, cy = x + 68 * s, y + 18 * s
        parts.append(circle(cx, cy, 14 * s, '#F8E6E3', deny))
        parts.append(path(f'M{cx - 5 * s} {cy - 5 * s} L{cx + 5 * s} {cy + 5 * s}', deny, 3))
        parts.append(path(f'M{cx + 5 * s} {cy - 5 * s} L{cx - 5 * s} {cy + 5 * s}', deny, 3))
    return ''.join(parts)


def technical_asset(name, x, y, width, height):
    raw = (W / 'assets' / (name + '.svg')).read_text()
    return raw.replace('<svg ', f'<svg x="{x}" y="{y}" width="{width}" height="{height}" ', 1)


def technical_console(x, y, width=128, opacity=1):
    # Reusable, embedded offline vector; this helper is used only by slide 6.
    raw = (W / 'assets' / 'operator-console-technical.svg').read_text()
    raw = raw.replace('<svg ', f'<svg x="{x}" y="{y}" width="{width}" height="{width * .7}" opacity="{opacity}" ', 1)
    return raw


def alert_chip(x, y, w=300):
    return (rect(x, y, w, 56, pale, teal, 8)
            + text(x + 18, y + 36, 'ALERT · Launch detected', 20, navy, 'bold'))


slides = {}  # n -> (title, svg_str)
notes = {}   # n -> list of (label, text)

PRESERVE_SET = (1, 2, 4, 5, 8, 9, 10)
preserved_notes = json.loads((W / 'notes' / 'preserved-notes.json').read_text())
for n in PRESERVE_SET:
    raw = (D / f'slide-{n:02}.svg').read_text()
    pn = preserved_notes[str(n)]
    slides[n] = (pn['title'], raw)
    notes[n] = [tuple(p) for p in pn['notes']]

# ===== Slide 3: the problem today — custom wiring per recipient =====
t3 = 'Every new recipient means another custom connection.'
c = text(80, 91, 'THE PROBLEM TODAY', 22, teal, 'bold')
c += text(80, 160, t3, 46, navy, 'bold')

# Diagram panel hugs the flow; pain cards sit below with even space to the footer.
c += rect(80, 225, 1440, 315, soft, r=8)
c += rect(105, 243, 170, 32, white, line, 16)
c += text(190, 265, 'Typical pattern', 16, muted, 'bold', anchor='middle')

# Same satellite and ground-antenna assets as the use-case slide, scaled to this panel.
# Flow: satellite -> Ground link -> Kafka, then the existing fan-out.
kafka_cy = 410
sat_w, sat_h = 168, 112
sat_x, sat_y = 110, kafka_cy - sat_h / 2
c += technical_asset('satellite-technical', sat_x, sat_y, sat_w, sat_h)
c += text(sat_x + sat_w / 2, sat_y + sat_h + 22, 'Launch detected', 18, muted, anchor='middle')

c += path(f'M{sat_x + sat_w + 8} {kafka_cy}H{sat_x + sat_w + 40}', teal, 3, end=True)

dish_w, dish_h = 168, 112
dish_x, dish_y = sat_x + sat_w + 48, sat_y
c += technical_asset('ground-antenna-technical', dish_x, dish_y, dish_w, dish_h)
c += text(dish_x + dish_w / 2, dish_y + dish_h + 22, 'Ground link', 18, muted, anchor='middle')

c += path(f'M{dish_x + dish_w + 8} {kafka_cy}H{dish_x + dish_w + 40}', teal, 3, end=True)

kafka_x, kafka_w, kafka_h = dish_x + dish_w + 48, 220, 130
kafka_y = kafka_cy - kafka_h / 2
kafka_right = kafka_x + kafka_w
c += rect(kafka_x, kafka_y, kafka_w, kafka_h, navy, r=4)
c += text(kafka_x + kafka_w / 2, kafka_cy - 18, 'Kafka', 28, white, 'bold', anchor='middle')
c += text(kafka_x + kafka_w / 2, kafka_cy + 18, ['Retained log', 'History · analytics'], 18, aqua, leading=1.25, anchor='middle')

# Three even rows inside the panel (80–1520). One elbow or straight arrow
# from Kafka's right edge to each wiring box; consumer sits to the right.
# No crossings, no dashed loops, no lines over or under other boxes.
box_x, box_w, box_h = 850, 330, 60
cons_x = 1220
box_cys = [330, 410, 490]  # even 80px pitch; labels stay above the panel bottom (540)
edge_ys = [370, 410, 450]  # start points along Kafka's right edge
consumers = ['Ops console', 'Analyst tool', 'Ticket system']
for i, (cy, ey, lab) in enumerate(zip(box_cys, edge_ys, consumers)):
    by = cy - box_h / 2
    c += path(f'M{kafka_right} {ey}H{kafka_right + 28}V{cy}H{box_x}', teal, 3, end=True)
    c += rect(box_x, by, box_w, box_h, white, line, 4)
    c += text(box_x + box_w / 2, cy + 8, 'App wiring ' + chr(65 + i), 22, muted, 'bold', anchor='middle')
    c += path(f'M{box_x + box_w} {cy}H{cons_x - 8}', teal, 2.5, end=True)
    c += text(cons_x, cy + 8, lab, 22, navy, 'bold')

# Three integration-pain cards
pains = [
    (80, '01', 'App wiring', ['Each consumer has its own', 'custom path.']),
    (560, '02', 'Alert selection', ['Each path has to choose which', 'alerts it should see.']),
    (1040, '03', 'Delivery / disconnect handling', ['Each path has to handle an operator', 'or system going offline.']),
]
for x, num, title, body in pains:
    c += rect(x, 560, 440, 220, pale, r=8)
    c += text(x + 24, 612, num, 32, teal, 'bold')
    c += text(x + 24, 662, title, 22, navy, 'bold')
    c += text(x + 24, 708, body, 18, muted, leading=1.35)

c += foot(3)
slides[3] = (t3, svg(3, c, t3))
notes[3] = [
        ('What to show',
         'About 2 minutes. A typical pattern today: a Launch detected alert reaches Kafka over the ground link. Kafka keeps a retained log for history and analytics. Each ground application then builds its own path — app wiring A, B, and C — to the ops console, an analyst tool, and a ticket system.'),
        ('Key points',
         'Three integration pains show up on that path. App wiring: each new recipient needs another custom connection. Alert selection: each path has to choose which alerts it should see. Delivery and disconnect handling: each path has to handle an operator or system going offline. This is a typical pattern, not a claim about a specific customer architecture.'),
        ('Where Solace adds value',
         'The rest of the briefing shows a path that keeps Kafka for history and uses Solace to distribute matching alerts, so a new recipient does not require another custom connection.'),
        ('Likely questions',
         'How do new consumers get onboarded today, and how long does a new wiring path take? Who owns alert selection on each of those paths? Who handles delivery when an operator or system is offline?'),
    ]

# ===== Slide 6: guaranteed delivery — important alerts wait while a service is offline =====
t6 = 'Important alerts wait while a service is offline.'
# Header and card band match slide 5 now that the headline is one line.
c = text(80, 91, 'GUARANTEED DELIVERY', 22, teal, 'bold')
c += text(80, 160, t6, 46, navy, 'bold')
c += text(80, 219, 'Live updates can be missed. Important alerts wait in a queue until the service reconnects.', 26, muted)
c += rect(80, 270, 700, 480, soft, r=8)
c += text(430, 330, 'Live updates', 28, navy, 'bold', anchor='middle')
c += text(430, 365, 'Direct', 22, teal, 'bold', anchor='middle')
c += technical_asset('operator-seated-offline', 235, 382, 340, 217.22)
c += text(430, 630, 'Service offline', 22, muted, anchor='middle')
c += text(430, 669, 'Launch detected is not retained', 23, muted, anchor='middle')
c += text(430, 715, 'Missed while offline', 24, muted, 'bold', anchor='middle')
c += rect(820, 270, 700, 480, soft, r=8)
c += text(1170, 330, 'Important alerts', 28, navy, 'bold', anchor='middle')
c += text(1170, 365, 'Guaranteed · local queue', 22, teal, 'bold', anchor='middle')
c += technical_asset('operator-seated-offline', 835, 395, 235, 150.14)
c += text(955, 566, 'Service offline', 20, muted, anchor='middle')
c += rect(1100, 405, 370, 100, pale, teal, 4)
c += text(1285, 441, 'Solace queue', 26, teal, 'bold', anchor='middle')
c += text(1285, 479, 'Holds Launch detected', 23, navy, anchor='middle')
c += path('M1285 516V549', teal, 3, end=True)
c += technical_asset('operator-seated-launch', 1180, 550, 275, 175.7)
c += text(980, 668, 'After reconnect', 21, navy, 'bold', anchor='middle')
c += path('M1080 660H1170', teal, 3, end=True)
c += text(1285, 742, 'Delivered after reconnect', 21, navy, 'bold', anchor='middle')
c += rect(100, 765, 102, 34, '#D9F2EF', teal, 17)
c += text(151, 788, 'DEMO 3', 16, teal, 'bold', anchor='middle')
c += foot(6)
slides[6] = (t6, svg(6, c, t6))
notes[6] = [
        ('What to show',
         'About 2 minutes. Two pictures. On the left, live updates use Direct messaging: if the service is offline, the update can be missed. On the right, important alerts wait in a queue and arrive when the service reconnects.'),
        ('Key points',
         'Queued means a durable endpoint on the ground broker holds the message while the subscriber is offline and the upstream bridge stays up. Capacity, acknowledgement, redelivery, and permissions are configured separately. Direct messaging delivers a live update while the consumer is subscribed. Guaranteed messaging retains the alert on a durable endpoint until it is consumed or expires, and delivery is acknowledged. An upstream link or bridge outage is a separate case: the ground broker can hold only what it has already received.'),
        ('Where Solace adds value',
         'Durable queues keep important alerts for an operator or system that is currently offline, within configured capacity and retention.'),
        ('Likely questions',
         'What if the queue fills up? Capacity is configured per queue; when full, the broker can reject new Guaranteed messages back to the publisher so nothing is lost silently. What if the bridge itself goes down? The ground broker holds only what it already received; that leg needs its own queue on the cloud side. Could the operator get a duplicate? Delivery is acknowledged; a message redelivered after a disconnect is flagged as redelivered so the app can handle it.'),
        ('Sources',
         'https://docs.solace.com/Get-Started/message-delivery-modes.htm'),
    ]

# ===== Slide 7: Kafka + Solace — keep history, distribute alerts =====
t7 = 'Keep Kafka for history. Let Solace distribute the alerts.'
c = text(80, 91, 'PROPOSED PATH', 22, teal, 'bold')
c += text(80, 160, t7, 46, navy, 'bold')

c += rect(80, 220, 1440, 580, pale, r=8)

# Main flow, left and center; distribution stack on the right.
# Same ground-antenna asset and Ground link label as the use-case slide,
# inserted between the satellite and Kafka. Slightly tighter boxes so the
# whole chain still ends before the right-hand spine.
cy = 460
sat_w, sat_h = 160, 106.67
sat_x, sat_y = 100, cy - sat_h / 2
c += technical_asset('satellite-technical', sat_x, sat_y, sat_w, sat_h)
c += text(sat_x + sat_w / 2, sat_y + sat_h + 24, 'Launch detected', 18, muted, anchor='middle')

c += path(f'M{sat_x + sat_w + 8} {cy}H{sat_x + sat_w + 36}', teal, 4, end=True)

dish_w, dish_h = 160, 106.67
dish_x, dish_y = sat_x + sat_w + 44, sat_y
c += technical_asset('ground-antenna-technical', dish_x, dish_y, dish_w, dish_h)
c += text(dish_x + dish_w / 2, dish_y + dish_h + 24, 'Ground link', 18, muted, anchor='middle')

c += path(f'M{dish_x + dish_w + 8} {cy}H{dish_x + dish_w + 36}', teal, 4, end=True)

kafka_w, kafka_h = 210, 130
kafka_x, kafka_y = dish_x + dish_w + 44, cy - kafka_h / 2
c += rect(kafka_x, kafka_y, kafka_w, kafka_h, navy, r=4)
c += text(kafka_x + kafka_w / 2, cy - 18, 'Kafka', 28, white, 'bold', anchor='middle')
c += text(kafka_x + kafka_w / 2, cy + 18, ['Retained log', 'History · analytics'], 18, aqua, leading=1.25, anchor='middle')

c += path(f'M{kafka_x + kafka_w + 8} {cy}H{kafka_x + kafka_w + 36}', teal, 4, end=True)

bridge_w, bridge_h = 185, 90
bridge_x, bridge_y = kafka_x + kafka_w + 44, cy - bridge_h / 2
c += rect(bridge_x, bridge_y, bridge_w, bridge_h, white, teal, 4)
c += text(bridge_x + bridge_w / 2, cy - 8, 'Kafka bridge', 22, teal, 'bold', anchor='middle')
c += text(bridge_x + bridge_w / 2, cy + 22, 'Configure · auth', 16, muted, anchor='middle')

c += path(f'M{bridge_x + bridge_w + 8} {cy}H{bridge_x + bridge_w + 36}', teal, 4, end=True)

sol_w, sol_h = 220, 130
sol_x, sol_y = bridge_x + bridge_w + 44, cy - sol_h / 2
c += rect(sol_x, sol_y, sol_w, sol_h, white, teal, 4)
c += text(sol_x + sol_w / 2, cy - 18, 'Solace delivery', 24, teal, 'bold', anchor='middle')
c += text(sol_x + sol_w / 2, cy + 22, 'Routes matching alerts', 18, navy, anchor='middle')

# Seamless 3-way split after Solace delivery. One feeder (no arrowhead)
# meets a spine that starts at the top branch and ends at the bottom
# branch. Top and bottom are elbow corners, with no overshoot. Arrowheads
# only on the three branches. Same stroke width and miter joins.
# Destinations share a left edge so the three branch lengths are equal.
sw = 4
# Marker is sized in stroke widths, so a short branch is hidden under the
# arrowhead. Keep a visible shaft: spine sits a little left of the icons,
# and the tip ends in the icons' left padding, still short of the artwork.
spine = 1230
dest_x = 1270
arrow_end = dest_x + 8  # 1278; application artwork starts ~1289.5
top_y, mid_y, bot_y = 340, cy, 650

# Feeder into the spine, then up and out to Analyst tool — top is a true elbow.
c += path(f'M{sol_x + sol_w} {mid_y}H{spine}V{top_y}H{arrow_end}', teal, sw, end=True, join='miter')
# Lower half of the spine and out to Ops console — bottom is a true elbow.
c += path(f'M{spine} {mid_y}V{bot_y}H{arrow_end}', teal, sw, end=True, join='miter')
# Middle branch to Ticket system.
c += path(f'M{spine} {mid_y}H{arrow_end}', teal, sw, end=True)

c += technical_asset('application-technical', dest_x, 306, 100, 70)
c += text(1388, 348, 'Analyst tool', 18, navy, 'bold')

c += technical_asset('application-technical', dest_x, 426, 100, 70)
c += text(1388, 468, 'Ticket system', 18, navy, 'bold')

c += technical_asset('operator-seated-launch', dest_x, 580, 240, 153.33)
c += text(1388, 758, 'Ops console', 18, navy, 'bold', anchor='middle')

# Tagline under the left-hand flow, not under the operator
c += text(115, 700, ['Kafka retains event history.', 'Solace distributes alerts.'], 22, navy, 'bold', leading=1.3)

c += foot(7)
slides[7] = (t7, svg(7, c, t7))
notes[7] = [
        ('What to show',
         'About 2 minutes. The alert reaches Kafka over the ground link. Kafka still keeps a retained log for history and analytics. A configured Kafka bridge feeds selected alerts into Solace, which routes matching alerts to the ground teams — the analyst tool, the ticket system, and the ops console. Kafka retains event history. Solace distributes alerts.'),
        ('Key points',
         'This is coexistence, not a replacement of Kafka. Kafka remains the system of record for history and analytics. The pattern can reduce per-application wiring for the same alert class, match which consumer needs which alert, and handle delivery when an operator or system is offline. Connector authentication, topic mapping, and operations still exist. Solace Kafka Bridging embeds a Kafka Receiver and Kafka Sender in the software event broker. Bootstrap addresses, authentication, TLS, topic bindings, and Solace topic mapping are configured.'),
        ('Where Solace adds value',
         'Distribution of matching alerts to ground teams, including disconnect handling, while Kafka remains the system of record for history and analytics.'),
        ('Likely questions',
         'Are you replacing Kafka? No — Kafka and Solace coexist. Kafka keeps history; Solace distributes matching alerts. Which paths need to stay on Kafka? Where does onboarding a new consumer take the most effort today: wiring, authorization, or offline delivery?'),
        ('Sources',
         'https://kafka.apache.org/documentation/; https://docs.solace.com/Features/Kafka-Bridging/Kafka-Bridging-Overview.htm'),
    ]


# ===== Write outputs =====
writer = PdfWriter()
for n in range(1, 11):
    title, s = slides[n]
    out_svg = D / f'slide-{n:02}.svg'
    if n not in PRESERVE_SET:
        out_svg.write_text(s)
    else:
        s = out_svg.read_text()
        slides[n] = (title, s)
    pdf = D / f'slide-{n:02}.pdf'
    cairosvg.svg2pdf(bytestring=s.encode(), write_to=str(pdf))
    # CairoSVG omits PDF link annotations. Preserve explicit SVG source links
    # using source-declared viewBox rectangles; normal rebuild stays self-contained.
    svg_root = ET.fromstring(s)
    link_nodes = [el for el in svg_root.iter() if el.get('data-pdf-link-rect')]
    if link_nodes:
        linked = PdfWriter()
        linked.append(str(pdf))
        page = linked.pages[0]
        sx, sy = float(page.mediabox.width) / 1600, float(page.mediabox.height) / 900
        for el in link_nodes:
            x1, y1, x2, y2 = map(float, el.get('data-pdf-link-rect').split())
            linked.add_annotation(page_number=0, annotation=Link(
                rect=(x1*sx, (900-y2)*sy, x2*sx, (900-y1)*sy),
                url=el.get('href') or el.get('{http://www.w3.org/1999/xlink}href')))
        linked.write(str(pdf))
    writer.append(str(pdf))
writer.write(D / 'deck-preview.pdf')

start = (W / 'start.html').read_text()
css = re.search(r'<style>(.*?)</style>', start, re.S).group(1)
js = re.search(r'<script>(.*?)</script>', start, re.S).group(1)
notes_css = ('.notes{display:none}#notes-panel{display:none;position:fixed;left:0;right:0;bottom:0;max-height:34vh;overflow:auto;'
        'background:#0B1F2D;color:#E8F1F2;border-top:3px solid #087F83;padding:14px 28px 22px;font:16px/1.5 "Liberation Sans",sans-serif}'
        '#notes-panel h2{font-size:15px;color:#8FE3DA;margin:0 0 8px;letter-spacing:.04em}#notes-panel p{margin:0 0 8px;max-width:1100px}#notes-panel b{color:#8FE3DA}'
        'body.notes-on #notes-panel{display:block}body.notes-on{place-items:start center}body.notes-on .slide{width:min(100vw,177.7778*66vh/100)}'
        '@media print{#notes-panel,.notes{display:none!important}}')
notes_js = ("const panel=document.getElementById('notes-panel');function renderNotes(){const a=slides[n].querySelector('.notes');"
            "panel.innerHTML='<h2>SPEAKER NOTES · SLIDE '+(n+1)+' · press N to hide</h2>'+(a?a.innerHTML:'');}"
            "document.addEventListener('keydown',e=>{if(e.key==='n'||e.key==='N'){document.body.classList.toggle('notes-on');}renderNotes()});renderNotes();")
# Reuse the shell's base navigation only. Prior finished sources can carry a
# notes addon followed by a hash addon, so suffix-only trimming is not safe.
css = css.replace(notes_css, '')
js = js.replace(notes_js, '')
js = re.sub(r"window\.addEventListener\('hashchange',\(\)=>\{const next=.*?renderNotes\(\);\}\}\);", '', js)
css += notes_css
html = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Space-event alerts across separate environments</title><style>' + css + '</style>'
        '<body data-name="Solace · simplified use case">')
for n in range(1, 11):
    t, s = slides[n]
    nb = ''.join(f'<p><b>{escape(l)}:</b> {escape(x)}</p>' for l, x in notes[n])
    html += (f'<section class="slide{" active" if n == 1 else ""}" '
             f'aria-label="Slide {n}: {escape(t)}">{s}<aside class="notes">{nb}</aside></section>')
hash_js = ("window.addEventListener('hashchange',()=>{const next=Math.max(0,Math.min(slides.length-1,(parseInt(location.hash.slice(1))||1)-1));"
            "if(next!==n){n=next;show();renderNotes();}});")
html += ('<div id="notes-panel" aria-live="polite"></div>'
         '<span class="help">← → Navigate · N Notes · Ctrl/Cmd+P Print</span>'
         '<script>' + js + notes_js + hash_js + '</script></body></html>')
(D / 'solace-federal-deck.html').write_text(html)

print('built slides 1-10')
for n in range(1, 11):
    print(f'  {n:02}  {slides[n][0][:75]}')
