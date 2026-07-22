import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const API_BASE = '/api';

const AdminDashboard = () => {
  const { token, logout } = useAuth();
  const navigate = useNavigate();
  
  const [activeTab, setActiveTab] = useState('settings');
  const [settings, setSettings] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!token) {
      navigate('/admin/login');
      return;
    }
    fetchData();
  }, [token, activeTab]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      if (activeTab === 'settings') {
        const res = await fetch(`${API_BASE}/admin/provider-settings/`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) throw new Error('Failed to fetch settings');
        setSettings(await res.json());
      } else if (activeTab === 'events') {
        const res = await fetch(`${API_BASE}/calendar/events/`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.status === 503 || res.status === 500) {
           throw new Error('Google Calendar is not linked or an error occurred. Please link your calendar first.');
        }
        if (!res.ok) throw new Error('Failed to fetch events');
        setEvents(await res.json());
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLinkCalendar = async () => {
    try {
      const res = await fetch(`${API_BASE}/calendar/login/`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to fetch OAuth URL');
      const data = await res.json();
      window.location.href = data.auth_url; // Redirect to Google
    } catch (err) {
      alert(err.message);
    }
  };

  const handleSaveSettings = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/admin/provider-settings/`, {
        method: 'PATCH',
        headers: { 
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error('Failed to save settings');
      alert('Settings saved successfully!');
    } catch (err) {
      alert(err.message);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/admin/login');
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-sidebar admin-card" style={{ padding: '1.5rem' }}>
        <div className="chat-header">
          <div className="chat-header-info">
            <h1>Admin Dashboard</h1>
          </div>
        </div>
        <nav className="dashboard-nav">
          <button 
            className={`nav-btn ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            Provider Settings
          </button>
          <button 
            className={`nav-btn ${activeTab === 'events' ? 'active' : ''}`}
            onClick={() => setActiveTab('events')}
          >
            Upcoming Events
          </button>
        </nav>
        <div className="dashboard-actions">
          <button onClick={handleLinkCalendar} className="btn-secondary">
            🔗 Link Google Calendar
          </button>
          <button onClick={handleLogout} className="btn-danger">
            Logout
          </button>
        </div>
      </div>

      <div className="dashboard-main admin-card">
        {loading && <p>Loading data...</p>}
        {error && <div className="error-banner">{error}</div>}
        
        {!loading && activeTab === 'settings' && settings && (
          <form onSubmit={handleSaveSettings} className="settings-form">
            <h2>Working Hours Configuration</h2>
            <div className="form-group">
              <label>Provider Name</label>
              <input 
                type="text" 
                value={settings.provider_name} 
                onChange={e => setSettings({...settings, provider_name: e.target.value})}
              />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Work Start Time</label>
                <input 
                  type="time" 
                  value={settings.work_start} 
                  onChange={e => setSettings({...settings, work_start: e.target.value})}
                />
              </div>
              <div className="form-group">
                <label>Work End Time</label>
                <input 
                  type="time" 
                  value={settings.work_end} 
                  onChange={e => setSettings({...settings, work_end: e.target.value})}
                />
              </div>
            </div>
            <div className="form-group">
              <label>Timezone</label>
              <input 
                type="text" 
                value={settings.timezone} 
                onChange={e => setSettings({...settings, timezone: e.target.value})}
              />
            </div>
            <button type="submit" className="btn-primary">Save Settings</button>
          </form>
        )}

        {!loading && activeTab === 'events' && (
          <div className="events-view">
            <h2>Upcoming Appointments</h2>
            {events.length === 0 ? (
              <p>No upcoming events found.</p>
            ) : (
              <div className="events-list">
                {events.map((ev, idx) => (
                  <div key={idx} className="event-card">
                    <h3>{ev.summary}</h3>
                    <p><strong>Start:</strong> {new Date(ev.start.dateTime).toLocaleString()}</p>
                    <p><strong>End:</strong> {new Date(ev.end.dateTime).toLocaleString()}</p>
                    {ev.description && <p><strong>Reason:</strong> {ev.description}</p>}
                    <a href={ev.htmlLink} target="_blank" rel="noreferrer">View in Google Calendar</a>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default AdminDashboard;
