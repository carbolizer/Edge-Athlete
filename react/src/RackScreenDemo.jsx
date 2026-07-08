import { useState } from "react";
import RouteLauncher from "./RouteLauncher.jsx";
import "./RackScreenDemo.css";

const steps = ["idle", "starting", "lifting", "complete", "resting"];

const repVelocities = [0.94, 0.88, 0.82];

function StatusPill({ state }) {
  return <span className={`rack-demo-pill ${state}`}>{state === "starting" ? "starting..." : state}</span>;
}

function TopBar({ label, state }) {
  return (
    <header className="rack-demo-topbar">
      <span>{label}</span>
      <StatusPill state={state} />
    </header>
  );
}

function ProgressDots({ active }) {
  return (
    <div className="rack-demo-dots" aria-label={`Step ${active + 1} of ${steps.length}`}>
      {steps.map((step, index) => (
        <span key={step} className={index === active ? "active" : ""} />
      ))}
    </div>
  );
}

function IdleScreen({ onNext }) {
  return (
    <>
      <TopBar label="RACK 1" state="idle" />
      <main className="rack-demo-body idle-screen">
        <p className="rack-demo-session">Back Squat Day</p>
        <div className="athlete-avatar">JW</div>
        <h1>J. Williams</h1>
        <p className="muted">Varsity - Lower Body Block 3</p>

        <section className="prescription-card">
          <div><span>Exercise</span><strong>Back Squat</strong></div>
          <div><span>Sets</span><strong>5 sets x 3 reps</strong></div>
          <div><span>Load</span><strong>225 lbs</strong></div>
          <div><span>Target velocity</span><strong>0.75 - 0.90 m/s</strong></div>
        </section>

        <button className="wristband-target" aria-label="Tap wristband to start set" onClick={onNext}>B</button>
        <p className="muted">Tap wristband to start set</p>

        <div className="or-rule"><span>or</span></div>
        <button className="primary-action" onClick={onNext}>Start Set Manually</button>
      </main>
    </>
  );
}

function CountdownScreen({ count, onNext }) {
  const progress = count === 3 ? 100 : count === 2 ? 66 : 38;

  return (
    <>
      <TopBar label="RACK 1 - SET 3 OF 5" state="starting" />
      <main className="rack-demo-body centered-screen">
        <p className="overline">Get ready</p>
        <button className="countdown-ring" style={{ "--progress": `${progress}%` }} onClick={onNext}>
          <span>{count}</span>
        </button>
        <p className="muted">Bar loaded - 225 lbs</p>
        <span className="exercise-chip">Back Squat</span>
      </main>
      <ProgressDots active={1} />
    </>
  );
}

function LiftingScreen({ onNext }) {
  return (
    <>
      <TopBar label="RACK 1 - SET 3 OF 5" state="lifting" />
      <main className="rack-demo-body lifting-screen">
        <div className="lifting-stats-row">
          <div>
            <span className="muted label">Current velocity</span>
            <strong className="live-velocity">0.88 <small>m/s</small></strong>
          </div>
          <div className="elapsed">
            <span className="muted label">Elapsed</span>
            <strong>0:04</strong>
          </div>
        </div>
        <div className="velocity-progress"><span /></div>

        <div className="rep-focus">
          <strong>0:04</strong>
          <span>Reps</span>
          <b>1</b>
          <em>1</em>
        </div>

        <button className="secondary-action" onClick={onNext}>End Set</button>
      </main>
      <ProgressDots active={2} />
    </>
  );
}

function CompleteScreen({ onNext }) {
  return (
    <>
      <TopBar label="RACK 1 - SET 3 OF 5" state="complete" />
      <main className="rack-demo-body complete-screen">
        <p className="overline">Set complete</p>
        <h1>3 reps - 225 lbs</h1>
        <p className="muted">Back Squat</p>

        <section className="result-grid">
          <div><strong>0.88</strong><span>avg velocity m/s</span></div>
          <div><strong>0.94</strong><span>peak velocity m/s</span></div>
          <div><strong>3</strong><span>reps completed</span></div>
          <div><strong>8.4s</strong><span>set duration</span></div>
        </section>

        <section className="rep-card">
          <h2>Rep by rep</h2>
          {repVelocities.map((velocity, index) => (
            <div className="rep-row" key={velocity}>
              <span>Rep {index + 1}</span>
              <div><i className={index === 2 ? "warn" : ""} style={{ width: `${velocity * 82}%` }} /></div>
              <strong>{velocity.toFixed(2)}</strong>
            </div>
          ))}
        </section>

        <div className="complete-actions">
          <button className="danger-action">False set</button>
          <button className="primary-action" onClick={onNext}>Start rest timer</button>
        </div>
      </main>
      <ProgressDots active={3} />
    </>
  );
}

function RestScreen({ onNext }) {
  return (
    <>
      <TopBar label="RACK 1 - 2 SETS REMAINING" state="resting" />
      <main className="rack-demo-body rest-screen">
        <p className="overline">Rest</p>
        <strong className="rest-time">1:59</strong>
        <p className="muted">Recommended 90 - 120s rest</p>

        <section className="suggestion-card">
          <span>Suggested next set</span>
          <strong>225 lbs - target 0.80+ m/s</strong>
          <p>Velocity held well - maintain load</p>
        </section>

        <div className="set-progress-labels"><span>Sets</span><span>3 of 5 done</span></div>
        <div className="set-progress-bars">
          <span /><span /><span className="warn" /><span className="todo" /><span className="todo" />
        </div>

        <button className="primary-action" onClick={onNext}>Start Set 4</button>
      </main>
      <ProgressDots active={4} />
    </>
  );
}

function RackScreenDemo() {
  const [step, setStep] = useState(0);
  const [count, setCount] = useState(3);

  function nextStep() {
    if (step === 1 && count > 1) {
      setCount(count - 1);
      return;
    }
    setCount(3);
    setStep((step + 1) % steps.length);
  }

  return (
    <div className="rack-demo-shell">
      <RouteLauncher />
      <div className="rack-demo-phone">
        {step === 0 && <IdleScreen onNext={nextStep} />}
        {step === 1 && <CountdownScreen count={count} onNext={nextStep} />}
        {step === 2 && <LiftingScreen onNext={nextStep} />}
        {step === 3 && <CompleteScreen onNext={nextStep} />}
        {step === 4 && <RestScreen onNext={nextStep} />}
      </div>
    </div>
  );
}

export default RackScreenDemo;
