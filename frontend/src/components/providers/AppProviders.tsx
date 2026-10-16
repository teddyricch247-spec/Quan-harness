'use client';

import React from 'react';
import { AppProvider } from '../../context/AppContext';
import { AppShell } from '../layout/AppShell';

export const AppProviders: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return (
    <AppProvider>
      <AppShell>{children}</AppShell>
    </AppProvider>
  );
};
