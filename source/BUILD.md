# Rebuild the presentation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-render.txt
.venv/bin/python deck/build_deck.py
```

Requires Python 3 and the Cairo library.

- Slides 1, 2, 4, 5, and 8–10 come from the tracked `deck/slide-NN.svg` files, with titles and speaker notes in `notes/preserved-notes.json`.
- Slides 3, 6, and 7 are drawn by `deck/build_deck.py` (using `assets/`). The script writes `deck/slide-03.svg`, `deck/slide-06.svg`, and `deck/slide-07.svg` along with the HTML and PDF outputs.
- The generator writes `deck/solace-federal-deck.html` and `deck/deck-preview.pdf`.
- SVG anchors with `data-pdf-link-rect` become PDF URI annotations via pypdf.
- Shell CSS, navigation, and fonts come from `start.html`.
