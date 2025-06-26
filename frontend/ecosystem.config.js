module.exports = {
  apps: [{
    name: 'calvin-vault',
    script: 'npm',
    args: 'start',
    env: {
      PORT: 3001,
      NODE_ENV: 'production'
    }
  }]
}
