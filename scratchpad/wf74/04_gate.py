"""The proposed gate, run frame by frame over the whole corpus in capture order.

Two layers:
  service (stateless, absolute) -- decidable from one frame, no history, no model
  integration (history-relative) -- ratios to the trailing median of accepted frames
"""
import numpy as np
import gate_lib as G

DARK_FLOOR = 16.0          # mean_luminance
BLANK_FLOOR = 0.5          # mean_absolute_gradient
BLOWN_CEILING = 0.90       # clipped_pixel_fraction
LUM_BAND = (0.5, 2.0)      # ratio to trailing median
DETAIL_FLOOR = 0.5         # ratio to trailing median
WINDOW, WARMUP = 30, 10


def service_gate(r, light_state="on"):
    reasons = []
    if r["mean_luminance"] < DARK_FLOOR:
        reasons.append("too_dark")
    if r["mean_absolute_gradient"] < BLANK_FLOOR:
        reasons.append("low_detail")
    if r["clipped_pixel_fraction"] >= BLOWN_CEILING:
        reasons.append("overexposed")
    if light_state == "on" and "too_dark" in reasons:
        reasons.append("light_state_mismatch")
    return reasons


RELATIVE = {"exposure_excursion", "detail_collapse"}
RUN_CAP = 2  # a relative rail may reject at most two consecutive captures


def run(window=WINDOW, warmup=WARMUP, verbose=False):
    rows = G.build()
    lum_h, det_h = [], []
    results = []
    rel_streak = 0
    for r in rows:
        reasons = service_gate(r)
        if not reasons and len(lum_h) >= warmup:
            lr = r["mean_luminance"] / max(np.median(lum_h[-window:]), 1e-6)
            dr = r["mean_absolute_gradient"] / max(np.median(det_h[-window:]), 1e-6)
            if not (LUM_BAND[0] <= lr <= LUM_BAND[1]):
                reasons.append("exposure_excursion")
            if dr < DETAIL_FLOOR:
                reasons.append("detail_collapse")
            # A sustained excursion is a changed regime, not noise: re-anchor rather
            # than blind the camera forever.
            if reasons and set(reasons) <= RELATIVE:
                rel_streak += 1
                if rel_streak > RUN_CAP:
                    reasons = []
            else:
                rel_streak = 0
        else:
            lr = dr = None
        if not reasons:
            lum_h.append(r["mean_luminance"])
            det_h.append(r["mean_absolute_gradient"])
        results.append((r, reasons, lr, dr))
    return results


res = run()
print("REJECTED frames")
for r, reasons, lr, dr in res:
    if reasons:
        print(f"  {r['date']}  {r['segment']:18} {','.join(reasons)}")

clean = [(r, x) for r, x, _, _ in res if r["segment"] not in G.UNUSABLE_SEGMENTS]
print(f"\nfalse rejections among {len(clean)} clean frames: "
      f"{sum(1 for _, x in clean if x)}")
for seg in ("occlusion-1", "occlusion-2", "lights-off"):
    v = [(r, x) for r, x, _, _ in res if r["segment"] == seg]
    print(f"rejected in {seg:12}: {sum(1 for _, x in v if x)}/{len(v)}")

print("\nclosest approach to each rail (clean frames only, warm history):")
lr_lo = min((x for _, _, x, _ in res if x is not None), default=None)
lr_hi = max((x for _, _, x, _ in res if x is not None), default=None)
clean_l = [x for r, _, x, _ in res if x is not None and r["segment"] not in G.UNUSABLE_SEGMENTS]
clean_d = [d for r, _, _, d in res if d is not None and r["segment"] not in G.UNUSABLE_SEGMENTS]
print(f"  luminance ratio, clean frames: {min(clean_l):.3f} .. {max(clean_l):.3f}"
      f"   (rails {LUM_BAND[0]} / {LUM_BAND[1]}; margin {min(clean_l)/LUM_BAND[0]:.2f}x / {LUM_BAND[1]/max(clean_l):.2f}x)")
print(f"  detail ratio,    clean frames: {min(clean_d):.3f} .. {max(clean_d):.3f}"
      f"   (rail {DETAIL_FLOOR}; margin {min(clean_d)/DETAIL_FLOOR:.2f}x)")

print("\nsensitivity: false rejections among clean frames")
for w in (10, 20, 30, 60):
    for wu in (5, 10):
        r2 = run(window=w, warmup=wu)
        fp = sum(1 for r, x, _, _ in r2 if x and r["segment"] not in G.UNUSABLE_SEGMENTS)
        tp = sum(1 for r, x, _, _ in r2 if x and r["segment"] == "lights-off")
        print(f"  window={w:>2} warmup={wu:>2}: clean rejected {fp}, lights-off rejected {tp}/13")

print("\nabsolute-floor margins")
rows = G.build()
lit = [r for r in rows if r["segment"] != "lights-off"]
off = [r for r in rows if r["segment"] == "lights-off"]
print(f"  mean_luminance:          lights-off max {max(r['mean_luminance'] for r in off):.2f}"
      f" | floor {DARK_FLOOR} | usable min {min(r['mean_luminance'] for r in lit):.2f}")
print(f"  mean_absolute_gradient:  lights-off max {max(r['mean_absolute_gradient'] for r in off):.3f}"
      f" | floor {BLANK_FLOOR} | usable min {min(r['mean_absolute_gradient'] for r in lit):.3f}")
print(f"  clipped_pixel_fraction:  usable max {max(r['clipped_pixel_fraction'] for r in lit):.3f}"
      f" | ceiling {BLOWN_CEILING}")
print(f"  frames >5% clipped: {sum(1 for r in lit if r['clipped_pixel_fraction'] > 0.05)}/{len(lit)}")
