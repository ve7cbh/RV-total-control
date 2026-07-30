python3 << 'PYEOF'
path = "/home/ve7cbh/RV-total-control/config/nginx/rvtc_index.html"

with open(path) as f:
    content = f.read()

edits = []

# 1. Replace the Generator column placeholder HTML
old_html = '''      <!-- GENERATOR column -->
      <div class="detail-col" id="col-generator">
        <div class="card" style="flex:1;display:flex;align-items:center;justify-content:center;text-align:center">
          <div>
            <!-- FONT SIZE: "Generator" title -->
            <div class="card-label" style="font-size:13px;margin-bottom:6px">Generator</div>
            <!-- FONT SIZE: "pending install" text comes from .coming-soon in the CSS above, no inline override -->
            <div class="coming-soon">RS-485/3 slave 2<br>pending install</div>
          </div>
        </div>
      </div><!-- /col-generator -->'''

new_html = '''      <!-- GENERATOR column -->
      <div class="detail-col" id="col-generator">
        <div class="inv-hero" style="flex:0 0 auto">
          <div>
            <div class="card-label" style="font-size:13px;margin-bottom:4px">Generator (KWS-303L)</div>
            <span class="inv-mode-text" style="font-size:32px;color:var(--orange)"><span id="gen-power">\u2014</span><span style="font-size:13px;color:var(--muted);margin-left:4px">W</span></span>
          </div>
          <div class="inv-meta">
            <div class="im-row"><span>Volt</span><span class="iv orange" id="gen-voltage">\u2014</span><span>V</span></div>
            <div class="im-row"><span>Curr</span><span class="iv orange" id="gen-current">\u2014</span><span>A</span></div>
            <div class="im-row"><span>Freq</span><span class="iv" id="gen-frequency">\u2014</span><span>Hz</span></div>
            <div class="im-row"><span>PF</span><span class="iv green" id="gen-pf">\u2014</span><span>&nbsp;</span></div>
          </div>
        </div>
        <div class="col">
          <div class="row">
            <div class="card" style="flex:1">
              <div class="card-label" style="font-size:13px">Meter Temp</div>
              <div><span class="card-value orange" style="font-size:32px" id="gen-temp">\u2014</span><span class="card-unit">\u00b0C</span></div>
              <div class="card-sub" style="font-size:12px">Internal NTC</div>
            </div>
            <div class="card" style="flex:1">
              <div class="card-label" style="font-size:13px">Alarm</div>
              <div style="margin-top:4px"><span id="gen-alarm" class="card-value green" style="font-size:22px">\u2014</span></div>
              <div class="card-sub" style="margin-top:6px;font-size:12px">Energy: <span id="gen-energy">\u2014</span> kWh</div>
            </div>
          </div>
        </div>
      </div><!-- /col-generator -->'''

if old_html not in content:
    edits.append("FAILED: Generator placeholder HTML not found")
else:
    content = content.replace(old_html, new_html)
    edits.append("OK: Generator column HTML replaced")

# 2. Add lastGen + fetchGenerator() right after the lastGrid declaration
old_js = "const lastGrid = { power: undefined, voltage: undefined, current: undefined };"

new_js = old_js + '''
const lastGen = { power: undefined, voltage: undefined, current: undefined };

async function fetchGenerator() {
  try {
    const data = await queryInflux('generator');

    set('gen-power',     data.power,        0);
    set('gen-voltage',   data.voltage,      1);
    set('gen-current',   data.current,      3);
    set('gen-frequency', data.frequency,    2);
    set('gen-pf',        data.power_factor, 3);
    set('gen-energy',    data.energy_kwh,   3);
    set('gen-temp',      data.temperature,  1);

    const alarmEl = document.getElementById('gen-alarm');
    if (alarmEl) {
      const code = Math.round(data.alarm_code || 0);
      const alarmMap = {0:'\u2705 None', 1:'\u26a0\ufe0f Over Voltage', 2:'\u26a0\ufe0f Under Voltage',
                        4:'\u26a0\ufe0f Over Current', 32:'\ud83c\udf21\ufe0f Over Temp'};
      alarmEl.textContent = alarmMap[code] || `Code ${code}`;
      alarmEl.style.color = code === 0 ? 'var(--green)' : 'var(--red)';
    }

    lastGen.power = data.power;
    lastGen.voltage = data.voltage;
    lastGen.current = data.current;

  } catch(e) {
    console.error('Generator fetch error:', e);
  }
}'''

if old_js not in content:
    edits.append("FAILED: lastGrid declaration not found")
elif "const lastGen" in content:
    edits.append("SKIPPED: lastGen already present")
else:
    content = content.replace(old_js, new_js)
    edits.append("OK: lastGen + fetchGenerator() added")

# 3. Replace the hardcoded genActive = false
old_genactive = "  const genActive  = false;"
new_genactive = """  // Direct physical measurement from the generator meter itself, not the inverter's
  // unconfirmed status registers -- deliberately independent signal, per the project
  // convention of not trusting operating_mode/status bits that haven't been observed live.
  const genActive = !isNaN(lastGen.current) && lastGen.current > 0.5;"""

if old_genactive not in content:
    edits.append("FAILED: hardcoded genActive line not found")
else:
    content = content.replace(old_genactive, new_genactive)
    edits.append("OK: genActive now reads real generator current")

# 4. Replace the "Pending install" placeholder in updateActiveHero()
old_pending = """    colour = 'var(--orange)';
    label = 'Generator';
    watt = '\u2014';
    sub = 'Pending install';"""
new_pending = """    colour = 'var(--orange)';
    label = 'Generator';
    watt = (lastGen.power === undefined || isNaN(lastGen.power)) ? '\u2014' : Number(lastGen.power).toFixed(0);
    sub = (!isNaN(lastGen.voltage) && !isNaN(lastGen.current))
      ? `${Number(lastGen.voltage).toFixed(1)} V \u00b7 ${Number(lastGen.current).toFixed(3)} A`
      : '\u2014';"""

if old_pending not in content:
    edits.append("FAILED: 'Pending install' hero block not found")
else:
    content = content.replace(old_pending, new_pending)
    edits.append("OK: hero band now shows live generator values")

# 5. Add fetchGenerator() to the polling loop
old_poll = """fetchSolar();
fetchGrid();
fetchInverter();
setInterval(fetchSolar,    2000);
setInterval(fetchGrid,     2000);
setInterval(fetchInverter, 2000);"""
new_poll = """fetchSolar();
fetchGrid();
fetchGenerator();
fetchInverter();
setInterval(fetchSolar,    2000);
setInterval(fetchGrid,     2000);
setInterval(fetchGenerator,2000);
setInterval(fetchInverter, 2000);"""

if old_poll not in content:
    edits.append("FAILED: polling-loop block not found")
else:
    content = content.replace(old_poll, new_poll)
    edits.append("OK: fetchGenerator added to polling loop")

for e in edits:
    print(e)

if all(e.startswith("OK") or e.startswith("SKIPPED") for e in edits):
    with open(path, "w") as f:
        f.write(content)
    print("\\nAll edits applied successfully — file saved.")
else:
    print("\\nOne or more edits FAILED — file NOT saved, no changes made. Paste the FAILED lines above.")
PYEOF