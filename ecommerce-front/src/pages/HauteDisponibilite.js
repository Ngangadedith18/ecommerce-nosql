import React, { useState, useEffect, useRef } from 'react';
import {
  Box, Card, CardContent, Typography, Button, Chip, CircularProgress
} from '@mui/material';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import PowerOffIcon from '@mui/icons-material/PowerOff';
import PowerIcon from '@mui/icons-material/Power';
import axios from 'axios';

const API = axios.create({ baseURL: 'http://localhost:8000' });

const STATE_COLORS = {
  PRIMARY:   { bg: 'rgba(67,233,123,0.1)',  border: '#43E97B', text: '#43E97B' },
  SECONDARY: { bg: 'rgba(37,99,235,0.1)',   border: '#2563EB', text: '#2563EB' },
  DOWN:      { bg: 'rgba(255,101,132,0.1)', border: '#FF6584', text: '#FF6584' },
};

export default function HauteDisponibilite() {
  const [members,   setMembers]   = useState([]);
  const [events,    setEvents]    = useState([]);
  const [apiChecks, setApiChecks] = useState([]);
  const [loading,   setLoading]   = useState({});
  const prevMembers  = useRef([]);
  const blockPollRef = useRef(false);
  // On garde en mémoire les nœuds qu'on a manuellement stoppés
  const manualDownRef = useRef(new Set());

  const fetchStatus = async () => {
    if (blockPollRef.current) return;
    try {
      const res = await API.get('/mongodb/replicaset');
      const newMembers = res.data.members.map(m => {
        const nodeName = m.name.split(':')[0];
        // Si on a manuellement stoppé ce nœud, on force DOWN
        if (manualDownRef.current.has(nodeName)) {
          return { ...m, state: 'DOWN', health: 0 };
        }
        return m;
      });

      // Détecter changements de rôle (sauf pour les nœuds manuellement stoppés)
      newMembers.forEach(m => {
        const nodeName = m.name.split(':')[0];
        if (manualDownRef.current.has(nodeName)) return;
        const old = prevMembers.current.find(o => o.name === m.name);
        if (old && old.state !== m.state) {
          const msg = `⚡ ${nodeName} : ${old.state} → ${m.state}`;
          setEvents(ev => [{ msg, time: new Date().toLocaleTimeString() }, ...ev].slice(0, 10));
        }
      });

      prevMembers.current = newMembers;
      setMembers(newMembers);
    } catch (e) {}
  };

  const checkApi = async () => {
    const start = Date.now();
    try {
      await API.get('/health', { timeout: 3000 });
      const ms = Date.now() - start;
      setApiChecks(c => [{ ok: true, ms, time: new Date().toLocaleTimeString() }, ...c].slice(0, 8));
    } catch (e) {
      setApiChecks(c => [{ ok: false, ms: null, time: new Date().toLocaleTimeString() }, ...c].slice(0, 8));
    }
  };

  useEffect(() => {
    fetchStatus();
    checkApi();
    const t1 = setInterval(fetchStatus, 4000);
    const t2 = setInterval(checkApi, 3000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, []);

  const handleAction = async (node, action) => {
    setLoading(l => ({ ...l, [node]: true }));
    try {
      await API.post(`/mongodb/failover/${action}/${node}`);

      if (action === 'stop') {
        // Marquer comme manuellement stoppé
        manualDownRef.current.add(node);
        // Mise à jour immédiate
        setMembers(prev => prev.map(m =>
          m.name.startsWith(node)
            ? { ...m, state: 'DOWN', health: 0 }
            : m
        ));
        const msg = `🔴 ${node} stoppé — failover en cours...`;
        setEvents(ev => [{ msg, time: new Date().toLocaleTimeString() }, ...ev].slice(0, 10));

      } else {
        // Relancer — retirer du set des nœuds stoppés manuellement
        manualDownRef.current.delete(node);
        // Mise à jour immédiate en SECONDARY
        setMembers(prev => prev.map(m =>
          m.name.startsWith(node)
            ? { ...m, state: 'SECONDARY', health: 1 }
            : m
        ));
        const msg = `🟢 ${node} redémarré — resynchronisation...`;
        setEvents(ev => [{ msg, time: new Date().toLocaleTimeString() }, ...ev].slice(0, 10));
        // Refresh après resynchronisation
        setTimeout(fetchStatus, 8000);
        setTimeout(fetchStatus, 15000);
      }

    } catch (e) {
      setEvents(ev => [{ msg: `❌ Erreur sur ${node}`, time: new Date().toLocaleTimeString() }, ...ev].slice(0, 10));
    } finally {
      setLoading(l => ({ ...l, [node]: false }));
    }
  };

  return (
    <Box>
      {/* En-tête */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Démonstration Haute Disponibilité</Typography>
          <Typography variant="body2" color="text.secondary">
            Stoppez le nœud PRIMARY et observez l'élection automatique d'un nouveau PRIMARY
            en moins de 10 secondes — l'API continue de répondre pendant tout le processus.
          </Typography>
        </CardContent>
      </Card>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 2 }}>

        {/* Nœuds MongoDB */}
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="h6">Replica Set rs0</Typography>
              <Chip label="Live — 4s" size="small"
                icon={<FiberManualRecordIcon sx={{ fontSize: '10px !important', color: '#43E97B !important' }} />}
                sx={{ bgcolor: 'rgba(67,233,123,0.1)', color: '#43E97B' }} />
            </Box>

            {members.map((m, i) => {
              const c = STATE_COLORS[m.state] || STATE_COLORS.DOWN;
              const nodeName = m.name.split(':')[0];
              const isDown = m.state === 'DOWN';
              const isPrimary = m.state === 'PRIMARY';
              return (
                <Box key={i} sx={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  p: 1.5, mb: 1, borderRadius: 2,
                  bgcolor: c.bg, border: `2px solid ${c.border}`,
                  boxShadow: isPrimary ? `0 0 12px ${c.border}44` : 'none',
                  transition: 'all 0.5s ease',
                }}>
                  <Box>
                    <Typography variant="subtitle2" sx={{ color: c.text, fontWeight: 700 }}>
                      {nodeName}
                    </Typography>
                    <Chip label={m.state} size="small"
                      sx={{ bgcolor: c.border, color: '#fff', fontWeight: 700, fontSize: 10, mt: 0.5 }} />
                  </Box>
                  <Box>
                    {!isDown ? (
                      <Button size="small" variant="outlined" color="error"
                        startIcon={loading[nodeName] ? <CircularProgress size={14} /> : <PowerOffIcon />}
                        disabled={!!loading[nodeName]}
                        onClick={() => handleAction(nodeName, 'stop')}
                        sx={{ fontSize: 11 }}>
                        Stopper
                      </Button>
                    ) : (
                      <Button size="small" variant="outlined" color="success"
                        startIcon={loading[nodeName] ? <CircularProgress size={14} /> : <PowerIcon />}
                        disabled={!!loading[nodeName]}
                        onClick={() => handleAction(nodeName, 'start')}
                        sx={{ fontSize: 11 }}>
                        Relancer
                      </Button>
                    )}
                  </Box>
                </Box>
              );
            })}
          </CardContent>
        </Card>

        {/* Disponibilité API */}
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="h6">Disponibilité API</Typography>
              <Chip label="Ping — 3s" size="small"
                icon={<FiberManualRecordIcon sx={{ fontSize: '10px !important', color: '#2563EB !important' }} />}
                sx={{ bgcolor: 'rgba(37,99,235,0.1)', color: '#2563EB' }} />
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
              L'API doit continuer à répondre pendant le failover
            </Typography>
            {apiChecks.map((c, i) => (
              <Box key={i} sx={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                py: 0.6, borderBottom: '1px solid rgba(255,255,255,0.05)'
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <FiberManualRecordIcon sx={{ fontSize: 10, color: c.ok ? '#43E97B' : '#FF6584' }} />
                  <Typography variant="caption" color="text.secondary">{c.time}</Typography>
                </Box>
                <Typography variant="caption" sx={{ color: c.ok ? '#43E97B' : '#FF6584', fontWeight: 600 }}>
                  {c.ok ? `✓ ${c.ms}ms` : '✗ Timeout'}
                </Typography>
              </Box>
            ))}
          </CardContent>
        </Card>
      </Box>

      {/* Journal des événements */}
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>Journal des événements</Typography>
          {events.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              Aucun événement — stoppez un nœud pour déclencher un failover.
            </Typography>
          ) : (
            events.map((e, i) => (
              <Box key={i} sx={{
                display: 'flex', justifyContent: 'space-between',
                py: 0.8, borderBottom: '1px solid rgba(255,255,255,0.05)'
              }}>
                <Typography variant="body2">{e.msg}</Typography>
                <Typography variant="caption" color="text.secondary">{e.time}</Typography>
              </Box>
            ))
          )}
        </CardContent>
      </Card>
    </Box>
  );
}