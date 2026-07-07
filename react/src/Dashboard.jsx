import { useState, useEffect, useCallback } from "react";
import "./App.css";
import Timeline from "./Timeline.jsx";
import StatisticsView from "./StatisticsView.jsx";

const API_BASE = "/api";

function formatTime(value) {
  if (!value) return "unknown time";
  return new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Dashboard({ onSensorChange }) {
  const [devices, setDevices] = useState([]);
  const [events, setEvents] = useState([]);
  const [selectedSensor, setSelectedSensor] = useState("all");
  const [showSettings, setShowSettings] = useState(false);
  const [deleteMode, setDeleteMode] = useState(false);
  const [sensorToDelete, setSensorToDelete] = useState(null);
  const [status, setStatus] = useState("Loading...");
  const [activeTab, setActiveTab] = useState("overview");
  const [testLoading, setTestLoading] = useState(false);
  const [testMessage, setTestMessage] = useState("");

  const loadData = useCallback(async () => {
    try {
      const eventPath =
        selectedSensor === "all"
          ? `${API_BASE}/events/`
          : `${API_BASE}/events/?node_id=${encodeURIComponent(selectedSensor)}`;

      const [devicesRes, eventsRes] = await Promise.all([
        fetch(`${API_BASE}/devices/`),
        fetch(eventPath),
      ]);

      if (!devicesRes.ok || !eventsRes.ok) throw new Error("API failed");

      const devicesData = await devicesRes.json();
      const eventsData = await eventsRes.json();

      setDevices(devicesData.devices || []);
      setEvents(eventsData.events || []);
      setStatus("Connected");
    } catch {
      setStatus("API offline");
    }
  }, [selectedSensor]);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 5000);
    return () => clearInterval(timer);
  }, [loadData]);

  async function removeDevice(nodeId) {
    await fetch(`${API_BASE}/devices/${encodeURIComponent(nodeId)}/`, {
      method: "DELETE",
    });
    if (selectedSensor === nodeId) setSelectedSensor("all");
    setSensorToDelete(null);
    setDeleteMode(false);
    loadData();
  }

  async function addTestEvent() {
    if (selectedSensor === "all") return;
    setTestLoading(true);
    setTestMessage("");
    try {
      const payload = {
        event_id: "test-" + Date.now(),
        node_id: selectedSensor,
        device_name: devices.find(d => d.node_id === selectedSensor)?.name || selectedSensor,
        location: "Dashboard test",
        connection: { interrupted: false, signal_strength: -55 },
        device_status: { battery: 88, firmware_version: "test" },
      };
      const res = await fetch(`${API_BASE}/motion/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || "request failed");
      loadData();
      setTestMessage("ok");
      setTimeout(() => setTestMessage(""), 3000);
    } catch (err) {
      setTestMessage(err.message);
    } finally {
      setTestLoading(false);
    }
  }

  const selectedDevice = devices.find((d) => d.node_id === selectedSensor);

  return (
    <div className="app">
      <div className="settings-container">
        <button onClick={() => setShowSettings(!showSettings)}>⚙️</button>
        {showSettings && (
          <div className="dropdown">
            <button
              onClick={() => {
                setDeleteMode(!deleteMode);
                setShowSettings(false);
              }}
            >
              {deleteMode ? "Done deleting" : "Delete Sensor"}
            </button>
          </div>
        )}
      </div>

      <div className="sidebar">
        <button
          className="sensor-button"
          onClick={() => { setSelectedSensor("all"); onSensorChange?.("All Sensors"); }}
        >
          <span>All Sensors</span>
          <span className="status online" />
        </button>

        {devices.map((device) => (
          <button
            key={device.node_id}
            className="sensor-button"
            onClick={() => { setSelectedSensor(device.node_id); onSensorChange?.(device.name); }}
          >
            <span>
              {device.name}
              <small style={{ display: "block", fontSize: "0.7em", color: "#aaa" }}>
                {device.node_id}
              </small>
            </span>
            {deleteMode ? (
              <button
                className="delete-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setSensorToDelete(device.node_id);
                }}
              >
                ❌
              </button>
            ) : (
              <span className={`status ${device.is_online ? "online" : "offline"}`} />
            )}
          </button>
        ))}
      </div>

      <div className="main">
        <div className="main-header">
          <h2 className="main-title">{selectedDevice ? selectedDevice.name : "All Sensors"}</h2>
          <button
            className="test-event-button"
            disabled={selectedSensor === "all" || testLoading}
            onClick={addTestEvent}
          >
            {testLoading ? "Sending..." : "Add Test Event"}
          </button>
        </div>

        <p style={{ color: "#888", fontSize: "0.85em", margin: "0 0 8px" }}>{status}</p>

        {testMessage && (
          <p className={testMessage === "ok" ? "test-event-hint ok" : "test-event-hint err"}>
            {testMessage === "ok" ? "Test event added." : testMessage}
          </p>
        )}

        <div className="tab-bar">
          <button
            className={"tab" + (activeTab === "overview" ? " active" : "")}
            onClick={() => setActiveTab("overview")}
          >
            Overview
          </button>
          <button
            className={"tab" + (activeTab === "statistics" ? " active" : "")}
            onClick={() => setActiveTab("statistics")}
          >
            Statistics
          </button>
        </div>

        {activeTab === "overview" ? (
          events.length === 0 ? (
            <p>No motion events yet.</p>
          ) : (
            <Timeline events={events} selectedSensor={selectedDevice ? selectedDevice.name : "All Sensors"} />
          )
        ) : (
          <StatisticsView events={events} selectedSensor={selectedDevice ? selectedDevice.name : "All Sensors"} />
        )}
      </div>

      {sensorToDelete && (
        <div className="modal-overlay">
          <div className="modal">
            <p>Are you sure you want to delete {sensorToDelete}?</p>
            <button onClick={() => removeDevice(sensorToDelete)}>Yes, Delete</button>
            <button onClick={() => setSensorToDelete(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;