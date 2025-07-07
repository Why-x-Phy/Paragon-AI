/** @type {import('tailwindcss').Config} */
export default {
    content: [
      './pages/**/*.{js,ts,jsx,tsx,mdx}',
      './components/**/*.{js,ts,jsx,tsx,mdx}',
      './app/**/*.{js,ts,jsx,tsx,mdx}',
    ],
    theme: {
      extend: {
        colors: {
          primary: '#B73E15',
          secondary: '#6B6969',
        },
        fontFamily: {
          orbitron: ['Orbitron', 'sans-serif'],
        },
      },
    },
    plugins: [],
  }