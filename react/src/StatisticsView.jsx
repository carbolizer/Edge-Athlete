// stats tab - line chart for one sensor, bar chart for all sensors
// each "activation" is just counting motion events from the api

const HOURS = 24;
const MS_PER_HOUR = 60 * 60 * 1000;

// svg layout (extra padding so numbers/labels aren't on top of the axes)
const CHART_W = 640;
const CHART_H = 320;
const PAD_LEFT = 88;
const PAD_RIGHT = 52;
const PAD_TOP = 36;
const PAD_BOTTOM = 80;

const Y_LABEL_GAP = 20; // space between y-axis line and tick numbers
const X_LABEL_INSET = 12; // keep -24h / now away from chart edges
const X_TICK_BELOW = 24; // time labels below the x-axis
const X_TITLE_BELOW = 52; // "Time" / "Sensors" under those labels

function getPlotArea() {
  const left = PAD_LEFT;
  const top = PAD_TOP;
  const width = CHART_W - PAD_LEFT - PAD_RIGHT;
  const height = CHART_H - PAD_TOP - PAD_BOTTOM;
  return {
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
  };
}

// figure out y axis max and helper to convert count -> pixel
function setupYAxis(maxCount, plot) {
  let yMax = 1;
  if (maxCount > 0) {
    yMax = Math.max(maxCount + 1, Math.ceil(maxCount * 1.12));
  }

  function countToY(count) {
    return plot.bottom - (count / yMax) * plot.height;
  }

  let tickValues = [0, Math.ceil(yMax / 2), yMax];
  if (yMax <= 1) tickValues = [0, 1];

  return { countToY, tickValues };
}

// grid + y axis labels + bottom axis line (used by both charts)
function ChartFrame({ plot, tickValues, countToY, yTitle }) {
  const labelX = plot.left - Y_LABEL_GAP;
  const yTitleX = PAD_LEFT / 2 - 4;

  return (
    <>
      <rect
        x={plot.left}
        y={plot.top}
        width={plot.width}
        height={plot.height}
        className="stat-plot-area"
      />

      {tickValues.map((val) => (
        <g key={val}>
          <line
            x1={plot.left}
            y1={countToY(val)}
            x2={plot.right}
            y2={countToY(val)}
            className="stat-grid-line"
          />
          <line
            x1={plot.left - 6}
            y1={countToY(val)}
            x2={plot.left}
            y2={countToY(val)}
            className="stat-axis-tick"
          />
          <text
            x={labelX}
            y={countToY(val)}
            className="stat-axis-label"
            textAnchor="end"
            dominantBaseline="middle"
          >
            {val}
          </text>
        </g>
      ))}

      <line
        x1={plot.left}
        y1={plot.top}
        x2={plot.left}
        y2={plot.bottom}
        className="stat-axis"
      />
      <line
        x1={plot.left}
        y1={plot.bottom}
        x2={plot.right}
        y2={plot.bottom}
        className="stat-axis"
      />

      <text
        x={yTitleX}
        y={plot.top + plot.height / 2}
        className="stat-axis-title"
        textAnchor="middle"
        transform={`rotate(-90 ${yTitleX} ${plot.top + plot.height / 2})`}
      >
        {yTitle}
      </text>
    </>
  );
}

// split events into 24 buckets, one per hour
function countPerHour(events) {
  const now = Date.now();
  const buckets = [];

  for (let i = 0; i < HOURS; i++) {
    buckets.push({ count: 0, hoursAgo: HOURS - 1 - i });
  }

  for (const ev of events) {
    const t = new Date(ev.detected_at).getTime();
    const hoursAgo = Math.floor((now - t) / MS_PER_HOUR);
    if (hoursAgo < 0 || hoursAgo >= HOURS) continue;
    const slot = HOURS - 1 - hoursAgo;
    buckets[slot].count += 1;
  }

  return buckets;
}

function LineChart({ buckets }) {
  const plot = getPlotArea();
  let maxCount = 0;
  for (const b of buckets) {
    if (b.count > maxCount) maxCount = b.count;
  }

  const { countToY, tickValues } = setupYAxis(maxCount, plot);
  const stepX = plot.width / (buckets.length - 1);

  let pointString = "";
  for (let i = 0; i < buckets.length; i++) {
    const x = plot.left + i * stepX;
    const y = countToY(buckets[i].count);
    pointString += x + "," + y + " ";
  }

  const timeLabelsY = plot.bottom + X_TICK_BELOW;
  const timeTitleY = plot.bottom + X_TITLE_BELOW;
  const xLeft = plot.left + X_LABEL_INSET;
  const xRight = plot.right - X_LABEL_INSET;

  return (
    <svg className="stat-chart" viewBox={`0 0 ${CHART_W} ${CHART_H}`}>
      <ChartFrame
        plot={plot}
        tickValues={tickValues}
        countToY={countToY}
        yTitle="Activation"
      />

      <text x={xLeft} y={timeLabelsY} className="stat-axis-label" textAnchor="start">
        -24h
      </text>
      <text
        x={plot.left + plot.width / 2}
        y={timeLabelsY}
        className="stat-axis-label"
        textAnchor="middle"
      >
        -12h
      </text>
      <text x={xRight} y={timeLabelsY} className="stat-axis-label" textAnchor="end">
        now
      </text>
      <text
        x={plot.left + plot.width / 2}
        y={timeTitleY}
        className="stat-axis-title"
        textAnchor="middle"
      >
        Time
      </text>

      <polyline points={pointString.trim()} className="stat-line" />

      {buckets.map((b, i) => {
        const x = plot.left + i * stepX;
        const y = countToY(b.count);
        return (
          <circle key={i} cx={x} cy={y} r={4} className="stat-point">
            <title>
              {b.hoursAgo}h ago: {b.count}
            </title>
          </circle>
        );
      })}
    </svg>
  );
}

function BarChart({ countsBySensor }) {
  const plot = getPlotArea();
  const names = Object.keys(countsBySensor);

  let maxCount = 0;
  for (const name of names) {
    if (countsBySensor[name] > maxCount) maxCount = countsBySensor[name];
  }

  const { countToY, tickValues } = setupYAxis(maxCount, plot);
  const slotWidth = plot.width / names.length;
  const barWidth = Math.max(12, slotWidth * 0.55);
  const labelY = plot.bottom + X_TICK_BELOW;
  const titleY = plot.bottom + X_TITLE_BELOW;

  return (
    <svg className="stat-chart" viewBox={`0 0 ${CHART_W} ${CHART_H}`}>
      <ChartFrame
        plot={plot}
        tickValues={tickValues}
        countToY={countToY}
        yTitle="Activation"
      />

      <text
        x={plot.left + plot.width / 2}
        y={titleY}
        className="stat-axis-title"
        textAnchor="middle"
      >
        Sensors
      </text>

      {names.map((name, i) => {
        const count = countsBySensor[name];
        const centerX = plot.left + i * slotWidth + slotWidth / 2;
        const barX = centerX - barWidth / 2;
        const barTop = countToY(count);
        const barHeight = plot.bottom - barTop;

        return (
          <g key={name}>
            <rect
              x={barX}
              y={barTop}
              width={barWidth}
              height={barHeight}
              rx={2}
              className="stat-bar"
            >
              <title>
                {name}: {count}
              </title>
            </rect>
            <text
              x={centerX}
              y={labelY}
              className="stat-axis-label stat-bar-label"
              textAnchor="middle"
            >
              {name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function StatisticsView({ events, selectedSensor }) {
  const now = Date.now();
  const dayAgo = now - HOURS * MS_PER_HOUR;

  // only look at events from last 24 hours
  const recent = [];
  for (const ev of events) {
    if (new Date(ev.detected_at).getTime() >= dayAgo) {
      recent.push(ev);
    }
  }

  // all sensors view - bar chart
  if (selectedSensor === "All Sensors") {
    const counts = {};
    for (const ev of recent) {
      const name = ev.device_name || "Node " + ev.node_id;
      if (!counts[name]) counts[name] = 0;
      counts[name] += 1;
    }

    const hasData = Object.keys(counts).length > 0;

    return (
      <div className="stat-view">
        <h3 className="stat-title">Activations per sensor (last 24h)</h3>
        {!hasData ? (
          <p className="stat-empty">Nothing in the last 24 hours.</p>
        ) : (
          <BarChart countsBySensor={counts} />
        )}
      </div>
    );
  }

  // single sensor - line chart + total card
  const forThisSensor = recent.filter(
    (ev) => ev.device_name === selectedSensor
  );
  const buckets = countPerHour(forThisSensor);
  const total = forThisSensor.length;
  const avgPerHour = (total / HOURS).toFixed(1);

  return (
    <div className="stat-view">
      <h3 className="stat-title">{selectedSensor} - activation over time</h3>
      <LineChart buckets={buckets} />

      <div className="stat-card">
        <div className="stat-card-label">Average Activation in 24 hrs</div>
        <div className="stat-card-value">{total}</div>
        <div className="stat-card-sub">~{avgPerHour} per hour</div>
      </div>
    </div>
  );
}

export default StatisticsView;
