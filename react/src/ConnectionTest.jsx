/*
 * ConnectionTest.jsx — Connection testing component for diagnostics
 * --------------------------------
 * This page is for testing all services are running
 *
 * Current state: Sprint 1 placeholder
 * This page confirms the React container is running and
 * reachable via Nginx. The actual dashboard UI will be
 * built in a later sprint.
 *
 * Works with:
 *   - nginx/nginx.conf — proxies all non-api requests here
 *   - django/event_handler/views.py — will fetch event data from here
 */

function ConnectionTest() {
  return (
    <div style={{ padding: '40px', fontFamily: 'monospace' }}>

      <h1>Edge Athlete V2</h1>
      <h2>React Container is Running</h2>

      <hr />

      <h3>Container Info</h3>
      <p>Service: React Frontend</p>
      <p>Port: 5173</p>
      <p>Status: Online</p>

      <hr />

      <h3>Architecture</h3>
      <p> "React - Nginx (port 80) - Django (port 8000) - PostgreSQL" </p>
      <p> "ESP32 - Mosquitto (port 1883) - Django - Ntfy" </p>


      <h3> Test Cases</h3>

      <p> "open http://localhost" - Nginx is reachable and proxying React</p>
        <p> "open or curl http://localhost/api/events/" - django api reachable through nginx</p>
        <p> "open or curl http://localhost/api/motion/" - django api reachable through nginx</p> 
      <p> "open http://localhost:8080" - Test that ntfy is running </p>
      <p> " open http://localhost/admin/" - Test Django Admin page gives response" </p>
      <p>"open http://localhost/api/" - Test API call. Expect: Django response or Django 404.</p>
      <p> "open http://localhost:8080" - Test that ntfy is running </p>

      <h3> Run if changes made to django model</h3>
      <p>docker exec edgeathlete-django python manage.py makemigrations</p>
      <p>docker exec edgeathlete-django python manage.py migrate</p>
      <hr />

      <p style={{ color: 'gray' }}>
        Sprint 1 Placeholder — Dashboard UI coming in later sprint
      </p>

    </div>
  );
}

export default ConnectionTest;