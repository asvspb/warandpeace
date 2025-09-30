import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        include: ['tests/frontend/unit/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}'],
        exclude: [
            'node_modules',
            'dist',
            'build',
            'pgdata', // Исключаем директорию с данными PostgreSQL
            'venv',
            '.git'
        ],
        environment: 'jsdom', // Используем jsdom для тестирования DOM
        globals: true, // Включаем глобальные функции Vitest (test, describe, expect и т.д.)
    },
});