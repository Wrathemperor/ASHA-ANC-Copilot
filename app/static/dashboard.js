// PHC & ANM Supervisor Dashboard JavaScript
(function () {
  'use strict';

  let currentPatients = [];
  let currentFilter = 'ALL';
  let searchQuery = '';

  const elements = {
    metricTotalMothers: document.getElementById('metric-total-mothers'),
    metricHighRisk: document.getElementById('metric-high-risk'),
    metricOverdue: document.getElementById('metric-overdue'),
    metricPendingReferrals: document.getElementById('metric-pending-referrals'),
    villageGrid: document.getElementById('village-cards-grid'),
    triageTbody: document.getElementById('triage-tbody'),
    triageSearch: document.getElementById('triage-search'),
    filterPills: document.querySelectorAll('.filter-pill'),
    kpiCards: document.querySelectorAll('.kpi-card'),
    drawerModal: document.getElementById('patient-drawer-modal'),
    drawerTitle: document.getElementById('drawer-title'),
    drawerBody: document.getElementById('drawer-body'),
    closeDrawerBtn: document.getElementById('close-drawer-btn'),
  };

  async function loadSummary() {
    try {
      const res = await fetch('/api/supervisor/summary');
      if (!res.ok) throw new Error('Failed to load summary');
      const data = await res.json();

      elements.metricTotalMothers.textContent = data.total_mothers || 0;
      elements.metricHighRisk.textContent = data.high_risk_mothers || 0;
      elements.metricOverdue.textContent = data.overdue_visits || 0;
      elements.metricPendingReferrals.textContent = data.pending_referrals || 0;

      // Render villages
      elements.villageGrid.innerHTML = (data.villages || [])
        .map(
          (v) => `
        <div class="village-card">
          <div class="village-name">${escapeHtml(v.name)}</div>
          <div class="village-stats-row">
            <span class="v-badge v-total">${v.total_mothers} Mothers</span>
            <span class="v-badge v-high">${v.high_risk_mothers} High-Risk</span>
            <span class="v-badge v-overdue">${v.overdue_visits} Overdue</span>
          </div>
        </div>
      `
        )
        .join('');
    } catch (err) {
      console.error('Error loading supervisor summary:', err);
    }
  }

  async function loadPatients() {
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.set('query', searchQuery);
      if (currentFilter !== 'ALL' && currentFilter !== 'OVERDUE' && currentFilter !== 'REFERRALS') {
        params.set('risk_tier', currentFilter);
      }
      if (currentFilter === 'OVERDUE') {
        params.set('overdue_only', 'true');
      }

      const res = await fetch(`/api/supervisor/patients?${params.toString()}`);
      if (!res.ok) throw new Error('Failed to load patients');
      const data = await res.json();
      currentPatients = data.patients || [];
      renderTable();
    } catch (err) {
      console.error('Error loading patients:', err);
      elements.triageTbody.innerHTML = `<tr><td colspan="7" class="loading-cell text-red">Error loading register: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  function renderTable() {
    if (!currentPatients.length) {
      elements.triageTbody.innerHTML = `<tr><td colspan="7" class="loading-cell">No expectant mothers matching the selected criteria.</td></tr>`;
      return;
    }

    elements.triageTbody.innerHTML = currentPatients
      .map((item) => {
        const p = item.patient;
        const v = item.latest_visit;
        const scoreClass =
          item.risk_tier === 'HIGH'
            ? 'score-high'
            : item.risk_tier === 'MODERATE'
            ? 'score-mod'
            : 'score-low';

        // Vitals text
        let vitalsHtml = '<span class="text-muted">No visits recorded</span>';
        if (v) {
          const bpText = v.bp_systolic && v.bp_diastolic ? `${v.bp_systolic}/${v.bp_diastolic}` : '—/—';
          const hbText = v.hemoglobin ? `${v.hemoglobin} g/dL` : '—';
          const wtText = v.weight_kg ? `${v.weight_kg} kg` : '—';
          vitalsHtml = `
            <div class="vitals-summary">
              <div><strong>BP:</strong> ${bpText} mmHg</div>
              <div><strong>Hb:</strong> ${hbText} | <strong>Wt:</strong> ${wtText}</div>
              ${item.danger_count > 0 ? `<span class="danger-tag-pill">${item.danger_count} Danger Sign${item.danger_count > 1 ? 's' : ''}</span>` : ''}
            </div>
          `;
        }

        // Referral status badge
        const refStat = item.referral_status || 'NOT_REQUIRED';
        let refClass = 'ref-none';
        let refLabel = 'None';
        if (refStat === 'REFERRED' || item.referral_flag) {
          refClass = 'ref-referred';
          refLabel = 'Referred (Pending PHC)';
        } else if (refStat === 'ATTENDED_PHC') {
          refClass = 'ref-attended';
          refLabel = 'Attended PHC';
        } else if (refStat === 'RESOLVED') {
          refClass = 'ref-resolved';
          refLabel = 'Resolved';
        }

        return `
        <tr>
          <td>
            <div class="patient-cell">
              <a href="javascript:void(0)" class="patient-name-link" data-rch="${p.rch_id}">${escapeHtml(p.name)}</a>
              <span class="rch-tag">RCH: ${p.rch_id}</span>
              <span class="text-muted" style="font-size: 0.72rem;">Age: ${p.age || '—'} yrs</span>
            </div>
          </td>
          <td>
            <span class="village-pill">${escapeHtml(p.village || 'Rampur')}</span>
          </td>
          <td>
            <div class="gestation-cell">
              <strong>${v && v.gestational_weeks ? `${v.gestational_weeks} wks` : '—'}</strong>
              <span class="stage-badge">${getAncStageLabel(v ? v.gestational_weeks : null)}</span>
              ${item.is_overdue ? '<span class="overdue-tag">Overdue</span>' : ''}
            </div>
          </td>
          <td>${vitalsHtml}</td>
          <td>
            <div class="risk-badge-box">
              <div class="score-circle ${scoreClass}">${item.risk_score}</div>
              <div>
                <div class="risk-tier-label" style="color: ${item.risk_color};">${escapeHtml(item.risk_tier)} RISK</div>
                <div class="text-muted" style="font-size: 0.7rem;">${escapeHtml(item.risk_badge)}</div>
              </div>
            </div>
          </td>
          <td>
            <span class="ref-badge ${refClass}">${refLabel}</span>
          </td>
          <td>
            <div class="action-btns">
              <button class="action-btn-sm btn-primary-sm view-dossier-btn" data-rch="${p.rch_id}" type="button">Dossier &amp; Trends</button>
            </div>
          </td>
        </tr>
      `;
      })
      .join('');

    // Attach event listeners to dossier buttons
    document.querySelectorAll('.view-dossier-btn, .patient-name-link').forEach((btn) => {
      btn.addEventListener('click', () => {
        const rch = btn.getAttribute('data-rch');
        if (rch) openPatientDossier(rch);
      });
    });
  }

  function getAncStageLabel(weeks) {
    if (!weeks) return 'ANC 1';
    if (weeks <= 12) return 'ANC 1';
    if (weeks <= 26) return 'ANC 2';
    if (weeks <= 35) return 'ANC 3';
    return 'ANC 4';
  }

  async function openPatientDossier(rchId) {
    elements.drawerBody.innerHTML = '<div class="loading-cell">Loading complete longitudinal dossier, trajectories, and transcripts...</div>';
    elements.drawerModal.hidden = false;

    try {
      const res = await fetch(`/api/supervisor/patient/${rchId}`);
      if (!res.ok) throw new Error('Failed to load patient dossier');
      const data = await res.json();
      renderDossier(data);
    } catch (err) {
      elements.drawerBody.innerHTML = `<div class="loading-cell text-red">Error loading dossier: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderDossier(data) {
    const p = data.patient;
    const visits = data.visits || [];
    const risk = data.risk_assessment;
    elements.drawerTitle.textContent = `${p.name} — RCH: ${p.rch_id}`;

    // Generate Gauge SVG (0 to 100)
    const score = risk ? risk.score : 0;
    const gaugeAngle = (score / 100) * 180 - 90; // -90deg to +90deg
    const gaugeSvg = `
      <svg class="gauge-svg" viewBox="0 0 200 110">
        <!-- Background Arc -->
        <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#e2e8f0" stroke-width="16" stroke-linecap="round"/>
        <!-- Green Segment (0-30) -->
        <path d="M 20 100 A 80 80 0 0 1 68 36" fill="none" stroke="#10b981" stroke-width="16"/>
        <!-- Amber Segment (30-60) -->
        <path d="M 68 36 A 80 80 0 0 1 132 36" fill="none" stroke="#f59e0b" stroke-width="16"/>
        <!-- Red Segment (60-100) -->
        <path d="M 132 36 A 80 80 0 0 1 180 100" fill="none" stroke="#ef4444" stroke-width="16"/>
        <!-- Needle -->
        <g transform="translate(100, 100) rotate(${gaugeAngle})">
          <line x1="0" y1="0" x2="0" y2="-65" stroke="#0f172a" stroke-width="3" stroke-linecap="round"/>
          <circle cx="0" cy="0" r="6" fill="#0f172a"/>
        </g>
      </svg>
    `;

    // Render Trajectory Graphs
    const bpChartSvg = renderBpTrajectorySvg(risk ? risk.trajectories : []);
    const hbChartSvg = renderHbTrajectorySvg(risk ? risk.trajectories : []);

    // Render Risk Factors
    const factorsHtml = (risk && risk.factors ? risk.factors : [])
      .map((f) => {
        const itemClass = f.severity === 'critical' ? 'factor-crit' : f.severity === 'warning' ? 'factor-warn' : 'factor-adv';
        return `
        <div class="factor-item ${itemClass}">
          <div>
            <div class="factor-name">${escapeHtml(f.name)}</div>
            <div class="factor-ev">Evidence: "${escapeHtml(f.evidence)}"</div>
          </div>
          <span class="factor-pts">+${f.points} pts</span>
        </div>
      `;
      })
      .join('') || '<div class="text-muted" style="font-size: 0.8rem;">No elevated risk factors detected. Standard routine antenatal care.</div>';

    // Render Audio Transcripts & Speech Audit Trail
    const latestVisit = visits.length ? visits[visits.length - 1] : null;
    let transcriptsHtml = '<div class="text-muted">No voice transcripts recorded for this mother yet.</div>';
    if (latestVisit && (latestVisit.transcript_turn1 || (latestVisit.transcripts_json && latestVisit.transcripts_json.length))) {
      const items = latestVisit.transcripts_json && latestVisit.transcripts_json.length
        ? latestVisit.transcripts_json
        : [
            { turn: 1, role: 'asha_visit_note', transcript: latestVisit.transcript_turn1 },
            latestVisit.transcript_turn2 ? { turn: 2, role: 'followup_response', transcript: latestVisit.transcript_turn2 } : null,
          ].filter(Boolean);

      transcriptsHtml = items
        .map(
          (t) => `
        <div class="transcript-bubble">
          <div class="transcript-header">
            <span>TURN ${t.turn}: ${t.role === 'asha_visit_note' ? 'ASHA INITIAL VOICE RECORDING' : 'FOLLOW-UP CLARIFICATION RESPONSE'}</span>
            <span>GNANI PRISMA v3.0 STT</span>
          </div>
          <div class="transcript-body">"${escapeHtml(t.transcript)}"</div>
        </div>
      `
        )
        .join('');
    }

    elements.drawerBody.innerHTML = `
      <!-- Dossier Hero Banner -->
      <div class="dossier-hero">
        <div>
          <h3 class="dossier-patient-name">${escapeHtml(p.name)}</h3>
          <div class="dossier-meta-row">
            <span><strong>Age:</strong> ${p.age || '—'} yrs</span>
            <span><strong>Village:</strong> ${escapeHtml(p.village || 'Rampur')}</span>
            <span><strong>EDD:</strong> ${p.edd || 'Not provided'}</span>
            <span><strong>Total Visits:</strong> ${visits.length}</span>
          </div>
          <div class="dossier-action-banner">
            <strong>MoHFW Clinician Action:</strong> ${escapeHtml(risk ? risk.clinician_action : 'Routine care.')}
          </div>
        </div>
        <div class="gauge-wrapper">
          <span class="kpi-label">COMPOSITE RISK GAUGE</span>
          ${gaugeSvg}
          <div class="gauge-score-text" style="color: ${risk ? risk.color : '#10b981'};">${score}/100</div>
          <div class="gauge-tier-pill" style="background: ${risk ? risk.color : '#10b981'};">${risk ? risk.tier : 'LOW'} RISK</div>
        </div>
      </div>

      <!-- Longitudinal Trend Charts -->
      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-title">
            <span>Blood Pressure Trajectory</span>
            <span style="font-size: 0.72rem; color: #dc2626;">Threshold: 140/90 mmHg</span>
          </div>
          ${bpChartSvg}
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-dot" style="background: #2563eb;"></span> Systolic</span>
            <span class="legend-item"><span class="legend-dot" style="background: #0d9488;"></span> Diastolic</span>
            <span class="legend-item"><span class="legend-dot" style="background: #dc2626;"></span> Alert Line</span>
          </div>
        </div>

        <div class="chart-card">
          <div class="chart-title">
            <span>Hemoglobin Trajectory</span>
            <span style="font-size: 0.72rem; color: #d97706;">Moderate Anemia: &lt;10.0 g/dL</span>
          </div>
          ${hbChartSvg}
          <div class="chart-legend">
            <span class="legend-item"><span class="legend-dot" style="background: #0284c7;"></span> Hb g/dL</span>
            <span class="legend-item"><span class="legend-dot" style="background: #ef4444;"></span> Severe (&lt;7)</span>
            <span class="legend-item"><span class="legend-dot" style="background: #f59e0b;"></span> Moderate (&lt;10)</span>
          </div>
        </div>
      </div>

      <!-- Risk Factors Breakdown -->
      <div class="factors-card">
        <h4 class="factors-title">Identified Risk Breakdown &amp; Spoken Evidence</h4>
        <div class="factors-list">${factorsHtml}</div>
      </div>

      <!-- Audio Transcripts & Explainability Review -->
      <div class="audit-card">
        <h4 class="audit-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 18px; height: 18px;">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          </svg>
          Visit Voice Transcripts &amp; Clinical Extraction Proof
        </h4>
        ${transcriptsHtml}

        <div class="supervisor-signoff-bar">
          <div>
            ${
              latestVisit && latestVisit.verified_by_supervisor
                ? '<span class="sign-status">✓ Verified by Medical Officer / ANM</span>'
                : '<span class="text-muted" style="font-size: 0.8rem;">Pending Supervisor Review</span>'
            }
          </div>
          <div style="display: flex; gap: 0.5rem;">
            ${
              latestVisit && !latestVisit.verified_by_supervisor
                ? `<button class="action-btn-sm btn-primary-sm" id="verify-visit-btn" data-vid="${latestVisit.id}" type="button">Mark Clinician Verified</button>`
                : ''
            }
            ${
              latestVisit && latestVisit.referral_flag && latestVisit.referral_status !== 'RESOLVED'
                ? `<button class="action-btn-sm" id="resolve-referral-btn" data-vid="${latestVisit.id}" type="button">Mark Hospital Attended</button>`
                : ''
            }
          </div>
        </div>
      </div>
    `;

    // Bind action buttons in drawer
    const verifyBtn = document.getElementById('verify-visit-btn');
    if (verifyBtn) {
      verifyBtn.addEventListener('click', async () => {
        const vid = verifyBtn.getAttribute('data-vid');
        try {
          verifyBtn.disabled = true;
          verifyBtn.textContent = 'Verifying...';
          const r = await fetch(`/api/visits/${vid}/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ supervisor_notes: 'Verified by Supervisor via PHC Dashboard.' }),
          });
          if (r.ok) {
            openPatientDossier(p.rch_id);
            loadPatients();
            loadSummary();
          }
        } catch (e) {
          alert('Error verifying visit: ' + e.message);
        }
      });
    }

    const resolveBtn = document.getElementById('resolve-referral-btn');
    if (resolveBtn) {
      resolveBtn.addEventListener('click', async () => {
        const vid = resolveBtn.getAttribute('data-vid');
        try {
          resolveBtn.disabled = true;
          resolveBtn.textContent = 'Updating...';
          const r = await fetch(`/api/visits/${vid}/referral-status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referral_status: 'ATTENDED_PHC', supervisor_notes: 'Confirmed hospital attendance.' }),
          });
          if (r.ok) {
            openPatientDossier(p.rch_id);
            loadPatients();
            loadSummary();
          }
        } catch (e) {
          alert('Error updating referral: ' + e.message);
        }
      });
    }
  }

  // Pure SVG BP Sparkline Generator
  function renderBpTrajectorySvg(trajectories) {
    if (!trajectories || trajectories.length < 1) {
      return '<div class="text-muted" style="padding: 2rem; text-align: center;">Single visit record — trend curve will populate on subsequent visits.</div>';
    }

    const w = 400;
    const h = 130;
    const pad = 30;

    // Y scale: 50 to 180 mmHg
    const minY = 50;
    const maxY = 180;
    const scaleY = (val) => h - pad - ((val - minY) / (maxY - minY)) * (h - 2 * pad);

    // X scale based on visit index or gestational weeks
    const pointsCount = Math.max(trajectories.length, 2);
    const stepX = (w - 2 * pad) / (pointsCount - 1);

    // Alert threshold lines: 140 systolic (red), 90 diastolic
    const y140 = scaleY(140);
    const y90 = scaleY(90);

    const sysPoints = [];
    const diaPoints = [];

    trajectories.forEach((pt, i) => {
      const x = pad + i * stepX;
      if (pt.bp_systolic) sysPoints.push({ x, y: scaleY(pt.bp_systolic), val: pt.bp_systolic });
      if (pt.bp_diastolic) diaPoints.push({ x, y: scaleY(pt.bp_diastolic), val: pt.bp_diastolic });
    });

    const sysPoly = sysPoints.map((p) => `${p.x},${p.y}`).join(' ');
    const diaPoly = diaPoints.map((p) => `${p.x},${p.y}`).join(' ');

    return `
      <svg class="chart-svg" viewBox="0 0 ${w} ${h}">
        <!-- Grid & Threshold Lines -->
        <line x1="${pad}" y1="${y140}" x2="${w - pad}" y2="${y140}" stroke="#fca5a5" stroke-dasharray="4" stroke-width="1.5"/>
        <line x1="${pad}" y1="${y90}" x2="${w - pad}" y2="${y90}" stroke="#99f6e4" stroke-dasharray="4" stroke-width="1"/>
        <text x="${w - pad + 5}" y="${y140 + 4}" fill="#ef4444" font-size="9" font-family="sans-serif">140</text>
        <text x="${w - pad + 5}" y="${y90 + 4}" fill="#0d9488" font-size="9" font-family="sans-serif">90</text>

        <!-- Lines -->
        ${sysPoints.length > 1 ? `<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="${sysPoly}"/>` : ''}
        ${diaPoints.length > 1 ? `<polyline fill="none" stroke="#0d9488" stroke-width="2.5" points="${diaPoly}"/>` : ''}

        <!-- Dots -->
        ${sysPoints.map((p) => `<circle cx="${p.x}" cy="${p.y}" r="4" fill="#2563eb"/><text x="${p.x}" y="${p.y - 7}" font-size="9" font-weight="bold" text-anchor="middle" fill="#1e293b">${p.val}</text>`).join('')}
        ${diaPoints.map((p) => `<circle cx="${p.x}" cy="${p.y}" r="4" fill="#0d9488"/><text x="${p.x}" y="${p.y + 14}" font-size="9" font-weight="bold" text-anchor="middle" fill="#0f766e">${p.val}</text>`).join('')}
      </svg>
    `;
  }

  // Pure SVG Hemoglobin Sparkline Generator
  function renderHbTrajectorySvg(trajectories) {
    if (!trajectories || trajectories.length < 1) {
      return '<div class="text-muted" style="padding: 2rem; text-align: center;">Single visit record — Hb trajectory will populate on subsequent visits.</div>';
    }

    const w = 400;
    const h = 130;
    const pad = 30;

    // Y scale: 5 to 15 g/dL
    const minY = 5;
    const maxY = 15;
    const scaleY = (val) => h - pad - ((val - minY) / (maxY - minY)) * (h - 2 * pad);

    const pointsCount = Math.max(trajectories.length, 2);
    const stepX = (w - 2 * pad) / (pointsCount - 1);

    const y10 = scaleY(10.0);
    const y7 = scaleY(7.0);

    const hbPoints = [];
    trajectories.forEach((pt, i) => {
      const x = pad + i * stepX;
      if (pt.hemoglobin) hbPoints.push({ x, y: scaleY(pt.hemoglobin), val: pt.hemoglobin });
    });

    const hbPoly = hbPoints.map((p) => `${p.x},${p.y}`).join(' ');

    return `
      <svg class="chart-svg" viewBox="0 0 ${w} ${h}">
        <!-- Anemia thresholds -->
        <line x1="${pad}" y1="${y10}" x2="${w - pad}" y2="${y10}" stroke="#fde68a" stroke-dasharray="4" stroke-width="1.5"/>
        <line x1="${pad}" y1="${y7}" x2="${w - pad}" y2="${y7}" stroke="#fca5a5" stroke-dasharray="4" stroke-width="1.5"/>
        <text x="${w - pad + 5}" y="${y10 + 4}" fill="#d97706" font-size="9" font-family="sans-serif">10.0</text>
        <text x="${w - pad + 5}" y="${y7 + 4}" fill="#ef4444" font-size="9" font-family="sans-serif">7.0</text>

        <!-- Hb Polyline -->
        ${hbPoints.length > 1 ? `<polyline fill="none" stroke="#0284c7" stroke-width="2.5" points="${hbPoly}"/>` : ''}

        <!-- Hb Dots -->
        ${hbPoints.map((p) => `<circle cx="${p.x}" cy="${p.y}" r="4" fill="#0284c7"/><text x="${p.x}" y="${p.y - 7}" font-size="9" font-weight="bold" text-anchor="middle" fill="#0369a1">${p.val}</text>`).join('')}
      </svg>
    `;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function bindEvents() {
    // Search input
    let searchDebounce;
    elements.triageSearch.addEventListener('input', (e) => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        searchQuery = e.target.value.trim();
        loadPatients();
      }, 250);
    });

    // Filter pills
    elements.filterPills.forEach((pill) => {
      pill.addEventListener('click', () => {
        elements.filterPills.forEach((p) => p.classList.remove('active'));
        pill.classList.add('active');
        currentFilter = pill.getAttribute('data-filter');
        loadPatients();
      });
    });

    // KPI cards click to filter
    elements.kpiCards.forEach((card) => {
      card.addEventListener('click', () => {
        const f = card.getAttribute('data-filter');
        elements.filterPills.forEach((p) => {
          if (p.getAttribute('data-filter') === f) p.click();
        });
      });
    });

    // Close drawer
    elements.closeDrawerBtn.addEventListener('click', () => {
      elements.drawerModal.hidden = true;
    });

    elements.drawerModal.addEventListener('click', (e) => {
      if (e.target === elements.drawerModal) {
        elements.drawerModal.hidden = true;
      }
    });
  }

  // Initial load
  loadSummary();
  loadPatients();
  bindEvents();
})();
