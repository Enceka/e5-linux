export default {darkMode: 'class', content: ['./index.html', './src/**/*.{ts,tsx}'], theme: {extend: {
  colors: {background: 'hsl(var(--background))', foreground: 'hsl(var(--foreground))',
    muted: 'hsl(var(--muted))', 'muted-foreground': 'hsl(var(--muted-foreground))',
    border: 'hsl(var(--border))', primary: 'hsl(var(--primary))', 'primary-foreground': 'hsl(var(--primary-foreground))',
    card: 'hsl(var(--card))', destructive: 'hsl(var(--destructive))'},
  borderRadius: {lg: '12px', md: '8px'}
}}, plugins: []};
