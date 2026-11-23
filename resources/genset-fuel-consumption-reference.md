# Diesel Genset Fuel Consumption — Reference

Source of truth for every physical constant in the FuelPay simulation engine.
If a number appears in `app/simulation/`, it should be traceable to this file.

---

## 1. Core consumption formula

```
fuel_L_per_hr = kVA × power_factor × load_fraction × SFC(load_fraction)
```

- `power_factor` — **0.8** is the industry-standard assumption for converting a
  genset's kVA (apparent power) nameplate rating to kW (real power).
  Stored per-generator so it can be overridden.
- `SFC` — Specific Fuel Consumption in **litres per kWh**. Not a constant; it
  varies with load because diesel engines burn proportionally more fuel when
  lightly loaded.

## 2. SFC curve

| Load % | SFC (L/kWh) |
|-------:|------------:|
|    25% |        0.35 |
|    50% |        0.30 |
|    75% |        0.26 |
|   100% |        0.24 |

Source: [waltpower.com — Diesel Generator Fuel Consumption Formula](https://waltpower.com/calculate-diesel-generator-fuel-consumption/)

**Implementation note:** linearly interpolate between these four points.
Below 25% load, hold SFC at 0.35 rather than extrapolating — extrapolation
diverges fast and light-load running is dominated by idle overhead anyway.

The same source gives a general figure of **0.25–0.30 L/kWh** under normal
operating load, which brackets the 50–75% band of the table. Consistent.

## 3. Validation against published vendor charts

The formula above was checked against independently published L/hr charts.
It reproduces them closely, which is why the engine is physics-based rather
than a lookup table — it generalises to any kVA rating in the 25–100 range.

| Genset  | Load | Formula result        | Published chart | Delta |
|---------|-----:|-----------------------|-----------------|-------|
| 100 kVA |  25% | 20 kW × 0.35 = 7.0    | 7 L/hr          | exact |
| 100 kVA |  50% | 40 kW × 0.30 = 12.0   | 12 L/hr         | exact |
| 100 kVA |  75% | 60 kW × 0.26 = 15.6   | 14–18 L/hr      | in range |
| 100 kVA | 100% | 80 kW × 0.24 = 19.2   | 18–25 L/hr      | in range |
| 25 kVA  |  25% | 5 kW × 0.35 = 1.75    | 2–3 L/hr        | slightly low |
| 25 kVA  |  50% | 10 kW × 0.30 = 3.0    | 3 L/hr          | exact |
| 25 kVA  |  75% | 15 kW × 0.26 = 3.9    | 5 L/hr          | slightly low |
| 25 kVA  | 100% | 20 kW × 0.24 = 4.8    | 6 L/hr          | slightly low |

Sources:
[asogenset.com](https://asogenset.com/diesel-generator-fuel-consumption-chart-real-world-examples/) ·
[fwpower.co.uk (PDF)](https://fwpower.co.uk/wp-content/uploads/2018/12/Diesel-Generator-Fuel-Consumption-Chart-in-Litres.pdf) ·
[generatorsource.com](https://generatorsource.com/tools-info/fuel-consumption-charts/)

### Known bias at the small end

The formula runs **~15–20% below** published charts for 25 kVA units, while
matching 100 kVA units almost exactly. This is expected and physically real:
small engines have worse specific fuel consumption than large ones, but the
published SFC curve is a single generic curve.

**Mitigation:** apply a size-efficiency factor that penalises smaller units.

```
size_penalty = 1 + 0.25 × (1 - (kVA - 25) / 75)      # 1.25 at 25 kVA → 1.00 at 100 kVA
```

This lifts 25 kVA @ 100% from 4.8 → 6.0 L/hr (chart says 6) and leaves
100 kVA untouched. Note this factor is a **fitted correction, not a sourced
constant** — it is calibrated to close the gap against the charts above.

Note also that published charts disagree with *each other* by 20–40% at the
same rating (100 kVA at full load is quoted as both 18 and 25 L/hr). Vendors
quote different engine families. Treat chart agreement within ±20% as good.
The upstream sources note actual use varies **±10%** by engine family, fuel
quality, load profile and site conditions even for one unit.

## 4. Tank capacity

Regulatory **minimums** (CPWD standards, via
[asogenset.com](https://asogenset.com/diesel-generator-fuel-consumption-chart-real-world-examples/)):

| Rating            | Minimum tank |
|-------------------|-------------:|
| up to 25 kVA      |       100 L  |
| 25 – 62.5 kVA     |       120 L  |
| 62.5 – 125 kVA    |       225 L  |

These are *minimums*, and they are small — 225 L on a 100 kVA unit at 50% load
(12 L/hr) is under 19 hours of runtime, which would mean near-daily refills.
Nothing anyone would fit a sensor to.

Real deployments size for autonomy, not for the minimum.
[AMPS](https://www.amps.org.uk/faqs/how-much-fuel-should-i-have/) frames tank
sizing in terms of required runtime rather than a fixed floor; a 1000 L tank
gives roughly 50 hours at 50% load.

### Two-tier storage

The regulatory table above describes only the generator's own in-built tank. A
Nigerian bank site — FuelPay's target customer — runs **two** tiers:

```
tanker  ->  BULK storage (5000 L+)  ->  DAY tank (in-built)  ->  engine
         delivery                   transfer               consumption
```

Bulk storage is a site asset, shared by every generator on it, and is where the
fuel and therefore the exposure sits. A site may run several bulk vessels
rather than one large one.

*Source: domain input from the project owner on the Nigerian bank market
(2026-08-07), not from the vendor literature above — the published sizing
guidance covers day tanks only.*

**The 1000 L floor.** FuelPay models no tank below 1000 L in either tier.
Smaller tanks exist in the field but are not the market, and instrumenting one
rarely pays for the hardware.

**Simulation defaults** — every tank is a `tanks` row with its own capacity:

| Site profile   | Day tank | Site bulk | Bulk tanks | Rationale                            |
|----------------|---------:|----------:|-----------:|--------------------------------------|
| bank branch    |   1500 L |   10000 L |          2 | the target customer; largest reserve |
| telecom tower  |   1000 L |    5000 L |          1 | unmanned, needs multi-day autonomy   |
| office         |   1000 L |    5000 L |          1 | serviced on a weekly round           |
| residential    |   1000 L |    5000 L |          1 | small estate                         |

Day tanks are nudged up for larger units so a 100 kVA set does not need topping
up twice as often as a 40 kVA one.

### Instrumentation

**A tank with no sensor does not exist to FuelPay.** This is an IoT platform: if
the object cannot be sensed, there is nothing to represent. So sensor fields on
a tank are mandatory, and there are no derived or estimated fuel levels
anywhere in the model.

The meaningful distinction is not sensor *presence* but sensor *signal*: a
probe that is installed and reporting versus one whose signal is lost. A gap in
the data is an absence of rows, never an interpolated line — see section 6.

Tanks are calibrated to their sensor at commissioning, so readings arrive in
litres; no raw-count conversion is stored.

## 5. Load profiles

Load is not constant — it is what drives the whole consumption curve.

| Profile        | Shape                                                        |
|----------------|--------------------------------------------------------------|
| telecom tower  | near-flat 65–75%, runs 24/7 — the classic always-on base load |
| office         | 20% overnight, ramping to 70–80% across business hours, weekday-biased |
| residential    | low daytime, sharp evening peak (~18:00–23:00) for lighting/AC |

Diesel engines run most efficiently at **50–75% load** — the SFC table shows
this directly (0.30 → 0.26 L/kWh), and the vendor sources call the 70–80% band
optimal. Profiles are centred to sit in that band during their peak.

## 6. Replenishment, drain and theft

### Transfer (bulk → day)
Triggered when the day tank falls below its **reorder threshold** (default 25%
of capacity). Pump-driven and therefore **not** confined to an hour window —
the top-up happens whenever the level drops and there is bulk fuel behind it.
Bounded by a pump rate (default 40 L/min), so a large day tank fills over
several ticks rather than jumping to full.

If every bulk tank on the site is dry, no transfer happens and a `LOW_FUEL`
event is raised instead. That state — a day tank running down with nothing
upstream — is the one worth alarming on.

### Delivery (tanker → bulk)
Triggered when a bulk tank falls below its threshold (default 30–40%, earlier
than a day tank: a tanker takes hours to arrive, and running the reserve dry
strands every generator on the site at once). Tops up to 90–100% of capacity —
not exactly 100%, since tankers deliver in whole units and drivers rarely fill
to the brim. Confined to working hours unless the tank is critical.

### Short delivery
The site is billed for one volume and receives a smaller one. This is the fraud
the bulk-tank sensor exists to expose: without a sensor on the receiving tank
there is no way to contest the invoice. Modelled at a default 12% of deliveries
losing 4–18% of the billed volume, with a 2% tolerance below which a shortfall
is treated as measurement slop rather than alleged as fraud.

*Source: domain input from the project owner (2026-08-07). Rates are chosen for
demonstrability, not measured — treat them as illustrative.*

### Theft / drain detection
The standard approach in the IoT fuel-monitoring literature is a
**rate-of-change threshold**: monitor the rate of fuel level change, and flag
when the drop exceeds a plausible-consumption threshold.

Sources:
[IEEE — IoT Enabled Fuel Level Monitoring and Automatic Fuel Theft Detection](https://ieeexplore.ieee.org/document/9984515/) ·
[DATOMS — Preventing Generator Fuel Theft with IoT](https://datoms.io/blogs/fuel-monitoring/the-role-of-iot-in-preventing-fuel-theft-and-pilferage-in-generators/)

Detection rule used here — flag a `SUSPECTED_DRAIN` when **either**:
1. fuel level drops while the engine is **not running** (burn rate should be 0), or
2. the drop rate exceeds **2× the maximum plausible burn rate** for that unit
   at 100% load.

Reported performance for such systems: **70–90%** of theft incidents identified
within 24 hours, with level-measurement accuracy of **98–99%** (DATOMS, IEEE).
The 2× multiplier gives headroom above sensor noise so normal running never
trips the rule.

### Simulated theft characteristics
- Rare — low probability per tank per day
- Fast — 20–40% of tank siphoned over 10–30 minutes
- Usually at night

**Which tier gets siphoned.** Bulk storage is the primary target: it holds far
more fuel and sits in its own compound. A day tank is modelled at 0.4× the
bulk rate, since it sits inside the genset housing.

**On the running-engine deterrent.** A running engine suppresses theft from the
day tank feeding it — the set is noisy, hot and usually attended. It does *not*
suppress theft from bulk storage. This distinction matters more than it looks:
telecom towers and bank branches run their generators continuously through an
outage, so gating bulk theft on the engine would make every 24/7 site immune —
i.e. exactly the sites the product exists to protect would never show an
incident.

### Signal loss and unverified loss
A sensor that stops reporting produces **no rows**, and that gap is never
interpolated across. This is the highest-risk window in the whole model: fuel
that disappears while nobody is watching cannot be attributed.

On reconnect the level drop across the gap is compared against the outflow
legitimately accounted for (burn for a day tank, transfers out for a bulk
tank). An unexplained remainder above 5% of capacity raises `UNVERIFIED_LOSS` —
deliberately *not* `SUSPECTED_DRAIN`, since with no observations through the
gap the data cannot distinguish theft from consumption. Asserting otherwise
would claim more than the evidence supports.

## 7. Sensor realism

Simulated readings are not the clean underlying truth. Layers applied:

| Effect        | Magnitude | Why |
|---------------|-----------|-----|
| sensor noise  | ±1% of capacity | capacitive/ultrasonic probes quote 98–99% accuracy (DATOMS) |
| sloshing      | ±0.5%, only while running | engine vibration disturbs the fuel surface |
| quantisation  | 0.1 L | probes report discrete steps, not infinite precision |
| GPS jitter    | ±5 m around fixed site position | gensets are static; only the fix wanders |

GPS jitter is modelled as a small random offset in metres converted to
degrees, not as a raw degree offset — a fixed degree offset would produce
distance error that changes with latitude.

---

## Summary of constants

| Constant | Value | Status |
|---|---|---|
| power factor | 0.8 | sourced |
| SFC @ 25/50/75/100% | 0.35 / 0.30 / 0.26 / 0.24 L/kWh | sourced |
| size penalty | 1.25 → 1.00 across 25–100 kVA | **fitted** |
| day tank reorder threshold | 25% of capacity | chosen |
| bulk reorder threshold | 30–40% of capacity | chosen |
| replenishment target | 90–100% of capacity | chosen |
| minimum modelled tank | 1000 L, both tiers | **domain input** |
| typical bulk tank | 5000 L+ | **domain input** |
| transfer pump rate | 40 L/min | chosen |
| short delivery rate | 12% of deliveries, 4–18% short | **chosen, illustrative** |
| short delivery tolerance | 2% of billed volume | chosen |
| day tank theft rate | 0.4× the bulk rate | chosen |
| sensor dropout | 4% per tank per day, 2–24 ticks | **chosen, illustrative** |
| unverified loss threshold | 5% of capacity across a gap | chosen |
| drain flag — engine off | any sustained drop | sourced (rate-of-change method) |
| drain flag — engine on | > 2× max burn rate | **chosen multiplier** |
| sensor noise | ±1% capacity | sourced (98–99% accuracy) |
| GPS jitter | ±5 m | chosen |
