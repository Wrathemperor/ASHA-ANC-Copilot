# Design System: ASHA ANC Copilot

## 1. Visual Theme & Atmosphere
A restrained, high-clarity clinical cockpit engineered specifically for high-stress frontline public health workers in rural and semi-urban India. The visual atmosphere balances "Porcelain Cleanroom" minimalism with warm, reassuring tactile physics — evocative of a high-end diagnostic instrument crafted by Dieter Rams or Teenage Engineering, rather than a bureaucratic government data portal or a flashy consumer AI demo.

- **Density:** 7.5 / 10 ("Diagnostic Cockpit") — Compact, high information efficiency without clutter. Clear visual separation between conversational intake and structured register verification.
- **Variance:** 6 / 10 ("Offset Asymmetric Architecture") — A slender 56px utility icon rail on the left, an interactive conversational stream in the primary column (60% width), and an evidence-backed clinical ledger with tri-state safety matrices on the right (40% width).
- **Motion:** 5 / 10 ("Tactile Restrained Feedback") — Hardware-accelerated transitions, subtle Indic speech recording waves, and smooth accordion reveals. No gratuitous 3D transforms or disorienting parallax.

---

## 2. Color Palette & Roles
All colors adhere to WCAG 2.2 AAA contrast standards for outdoor direct-sunlight readability on low-cost Android field tablets. Absolute neutral slate bases eliminate warm/cool gray inconsistency.

- **Canvas White** (`#F8FAFC`, Slate-50) — Primary full-viewport workspace background.
- **Porcelain Surface** (`#FFFFFF`) — High-elevation card containers, modals, and conversational bubbles.
- **Charcoal Ink** (`#0F172A`, Slate-900) — Primary clinical typography and header text. Never pure black (`#000000`).
- **Muted Steel** (`#64748B`, Slate-500) — Secondary metadata, timestamps, RCH IDs, and supporting labels.
- **Whisper Border** (`#E2E8F0`, Slate-200) — Precise 1px structural container and divider lines.
- **Subtle Surface Tint** (`#F1F5F9`, Slate-100) — Interactive hover states, badge fills, and audio wave track backgrounds.
- **Clinical Emerald [Singular Primary Accent]** (`#15803D`, Emerald-700 / `#16A34A`, Emerald-600) — Singular accent reserved strictly for active voice recording, confirmed safe vitals, send actions, and verified clinical statuses (Saturation 72%, strictly non-neon).
- **Tri-State Safety System:**
  - *Present (Acute Danger):* Rose Tint (`#FEF2F2`), Rose Stroke (`#FECACA`), Crimson Ink (`#991B1B`).
  - *Denied (Verified Absent):* Emerald Tint (`#F0FDF4`), Emerald Stroke (`#BBF7D0`), Forest Ink (`#166534`).
  - *Unknown (Silence is Never Denial):* Slate Tint (`#F8FAFC`), Slate Stroke (`#E2E8F0`), Muted Ink (`#64748B`).

*Strict Ban:* The "AI Purple/Blue Neon" aesthetic is strictly prohibited — no gradient glows, no cyan drop shadows, no neon button rings.

---

## 3. Typography Rules
- **Display & Headings:** `Space Grotesk` (weights 600, 700) or `Cabinet Grotesk` — Track-tight (`-0.02em`), confident, architectural geometry. Conveys institutional trust and authoritative clinical pedigree without shouting.
- **Body & Microcopy:** `Inter` or `Geist` (weights 400, 500) — Relaxed line height (`1.55`), maximum line length of 65 characters. Neutral secondary tint (`#334155`).
- **Clinical Monospace & Figures:** `JetBrains Mono` or `Geist Mono` (weights 500, 600) — Mandatory for all numerical clinical measurements (e.g., `120/80 mmHg`, `32 wks`, `54.2 kg`, `9.8 g/dL`), timestamps, 12-digit RCH identifiers, and MoHFW PMSMA protocol citations (`[ANC-01]`). Tabular figures (`font-variant-numeric: tabular-nums`) eliminate visual layout jitter during real-time value updates.
- **Banned:** Generic system serifs (`Times New Roman`, `Georgia`, `Garamond`), stylized cursive scripts, and oversized screaming headlines.

---

## 4. Component Stylings

### Conversational Chat & Input Dock
- **User Voice Note Bubbles:** Asymmetric rounded pill containers (`border-radius: 18px 18px 4px 18px`), filled with ultra-soft emerald tint (`#DCFCE7`), featuring play control icon, duration pill, and real-time verbatim Indic transcription.
- **Copilot Message Bubbles:** Crisp white cards (`border-radius: 18px 18px 18px 4px`) with 1px Slate-200 border, distinct clinical badge (`ASHA ANC Copilot`), and markdown-formatted clinical explanations.
- **WhatsApp-Style Composer Bar:** Fixed docked footer (`padding: 10px 14px`) with white background, subtle top border (`1px solid #E2E8F0`), paperclip attachment trigger, elastic textarea, and spring-animated toggle between Mic button and Send button.

### Clinical Cards & Registers
- **Elevation & Corners:** Generously restrained radius (`12px` to `16px`). Shadows are diffused ambient whispers (`box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)`).
- **Interactive Buttons:** Tactile flat styling with `-1px` vertical translate on active/press. Primary action button filled with solid Emerald-700 (`#15803D`) and high-contrast white text. Secondary buttons use ghost outlines with 1px Slate-200 borders.
- **Form Inputs:** Labels consistently positioned above inputs with uppercase `11px` monospace tracking (`letter-spacing: 0.05em`). Active focus rings use Emerald-600 (`outline: 2px solid #16A34A; outline-offset: 1px`). No floating label hacks.
- **Skeletal Loaders:** Geometric pulsating shimmer matching exact vitals card proportions. No generic spinning SVG circles.
- **Empty States:** Composed diagnostic cards with actionable prompts (e.g., "Press & hold mic to dictate clinical notes in Hindi, Marathi, Telugu, Tamil, Malayalam, or English").

---

## 5. Layout Principles & Responsive Grid
- **Architecture:** Grid-first responsive cockpit layout.
  - *Desktop (≥ 1024px):* 56px fixed porcelain utility rail + 2-column workspace split (`1.1fr` conversational intake : `0.9fr` clinical ledger). Maximum workspace containment of `1440px`.
  - *Tablet (768px – 1023px):* Single-column vertical stack with sticky vitals summary bar.
  - *Mobile (< 768px):* Strict single-column collapse. Full touch-first ergonomics with minimum `48px` tap targets for all thumb-accessible actions.
- **No Overlapping:** Elements occupy dedicated, deterministic spatial zones. Absolute-positioned content stacking is prohibited.
- **Viewport Height:** Full-height containers strictly utilize `min-height: 100dvh` (never `100vh` to prevent iOS/Android mobile browser address bar layout jumps).
- **Section Spacing:** Uniform 8px harmonic spacing grid (`8px`, `16px`, `24px`, `32px`).

---

## 6. Motion & Interaction Philosophy
- **Physics Calibration:** Spring physics feel (`stiffness: 120, damping: 20`) for modal entries and chat bubble appends. No linear or robotic easing curves.
- **Perpetual Micro-Interactions:**
  - *Recording Active:* Subtle pulsing emerald halo around the microphone button (`@keyframes mic-pulse`).
  - *Audio Spectrum:* Multi-bar SVG frequency equalizer animating dynamically during voice capture.
  - *Processing Shimmer:* Linear gradient wave sweep across unresolved register fields during Prisma STT and Evon LLM extraction.
- **Performance:** Animations restricted exclusively to `transform` and `opacity` properties to preserve 60 FPS rendering on budget MediaTek/Snapdragon field smartphones.

---

## 7. Anti-Patterns (Banned AI Slop Directives)
1. **No Emojis Anywhere in Production UI:** Replaced by precision monochrome SVG iconography (Feather/Lucide style, `1.75px` stroke).
2. **No Pure Black (`#000000`):** Always use Slate-900 (`#0F172A`) for deep, readable typographic hierarchy.
3. **No Neon / Outer Glow Effects:** No glowing purple buttons, cyber-blue outlines, or flashy gradient text on headlines.
4. **No Fabricated / Fake Statistics:** Never invent numbers like "99.98% Accuracy", "10,000+ Lives Saved", or "4.9/5 Rating" as design decoration. Real clinical data or clear bracketed indicators only.
5. **No AI Copywriting Clichés:** Strictly forbidden words: *"Elevate"*, *"Seamless"*, *"Unleash"*, *"Supercharge"*, *"Next-Gen"*, *"Revolutionary"*. Copy must remain clinical, precise, and operational.
6. **No 3-Column Equal Card Grids:** Banned in favor of hierarchical asymmetric layouts that reflect diagnostic urgency.
7. **No "Scroll to explore" or Bouncing Chevrons:** Spatial hierarchy and clear visual affordances pull the user naturally down the page.
8. **No Circular Loaders:** Replaced by structural inline shimmer waves matching exact target component bounds.
