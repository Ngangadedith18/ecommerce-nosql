import React, { useState } from 'react';
import { ThemeProvider, createTheme, CssBaseline, Box, Drawer, List,
  ListItemButton, ListItemIcon, ListItemText, Typography, AppBar, Toolbar, Chip } from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import StorefrontIcon from '@mui/icons-material/Storefront';
import RecommendIcon from '@mui/icons-material/Recommend';
import SettingsIcon from '@mui/icons-material/Settings';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StorageIcon from '@mui/icons-material/Storage';
import Dashboard from './pages/Dashboard';
import Catalogue from './pages/Catalogue';
import Recommandations from './pages/Recommandations';
import Pipeline from './pages/Pipeline';
import HauteDisponibilite from './pages/HauteDisponibilite';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary:   { main: '#6C63FF' },
    secondary: { main: '#FF6584' },
    background: { default: '#0F0F1A', paper: '#1A1A2E' },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", sans-serif',
    h4: { fontWeight: 700 },
    h6: { fontWeight: 600 },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiCard: {
      styleOverrides: {
        root: { backgroundImage: 'none', border: '1px solid rgba(108,99,255,0.15)' }
      }
    }
  }
});

const DRAWER_WIDTH = 240;
const PAGES = [
  { label: 'Dashboard',       icon: <DashboardIcon />,  component: <Dashboard /> },
  { label: 'Catalogue',       icon: <StorefrontIcon />, component: <Catalogue /> },
  { label: 'Recommandations', icon: <RecommendIcon />,  component: <Recommandations /> },
  { label: 'Haute Disponibilité', icon: <StorageIcon />, component: <HauteDisponibilite /> },
  { label: 'Pipeline',        icon: <SettingsIcon />,  component: <Pipeline /> },
];

export default function App() {
  const [page, setPage] = useState(0);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', minHeight: '100vh' }}>

        {/* Sidebar */}
        <Drawer variant="permanent" sx={{
          width: DRAWER_WIDTH,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            bgcolor: 'background.paper',
            borderRight: '1px solid rgba(108,99,255,0.15)',
            pt: 2,
          }
        }}>
          {/* Logo */}
          <Box sx={{ px: 3, pb: 3 }}>
            <Typography variant="h6" sx={{ color: 'primary.main', fontWeight: 800, letterSpacing: 1 }}>
              ◈ NoSQL Shop
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              E-Commerce Analytics
            </Typography>
          </Box>

          <List>
            {PAGES.map((p, i) => (
              <ListItemButton
                key={i}
                selected={page === i}
                onClick={() => setPage(i)}
                sx={{
                  mx: 1, borderRadius: 2, mb: 0.5,
                  '&.Mui-selected': {
                    bgcolor: 'rgba(108,99,255,0.15)',
                    '& .MuiListItemIcon-root': { color: 'primary.main' },
                    '& .MuiListItemText-primary': { color: 'primary.main', fontWeight: 700 },
                  }
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: 'text.secondary' }}>{p.icon}</ListItemIcon>
                <ListItemText primary={p.label} />
              </ListItemButton>
            ))}
          </List>

          {/* Status */}
          <Box sx={{ mt: 'auto', p: 2 }}>
            <Chip
              icon={<FiberManualRecordIcon sx={{ fontSize: '10px !important', color: '#4CAF50 !important' }} />}
              label="API connectée"
              size="small"
              sx={{ bgcolor: 'rgba(76,175,80,0.1)', color: '#4CAF50', border: '1px solid rgba(76,175,80,0.3)' }}
            />
          </Box>
        </Drawer>

        {/* Main content */}
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <AppBar position="static" elevation={0} sx={{
            bgcolor: 'background.paper',
            borderBottom: '1px solid rgba(108,99,255,0.15)',
          }}>
            <Toolbar>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {PAGES[page].label}
              </Typography>
            </Toolbar>
          </AppBar>

          <Box sx={{ flex: 1, p: 3, bgcolor: 'background.default', overflowY: 'auto' }}>
            {PAGES[page].component}
          </Box>
        </Box>

      </Box>
    </ThemeProvider>
  );
}