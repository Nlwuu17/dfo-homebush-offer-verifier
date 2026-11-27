import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir:'./e2e',
  use:{baseURL:'http://127.0.0.1:3000'},
  webServer:[
    {command:'python -m uvicorn v03.api:app --host 127.0.0.1 --port 8000',cwd:'..',url:'http://127.0.0.1:8000/api/cases',env:{DEEPSEEK_API_KEY:'',ANTHROPIC_API_KEY:''}},
    {command:'npm run start -- --hostname 127.0.0.1',url:'http://127.0.0.1:3000'}
  ]
});
