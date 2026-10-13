import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir:"./tests", timeout:30000, expect:{timeout:10000}, workers:1, retries:0,
  use:{baseURL:process.env.E2E_BASE_URL??"http://localhost:3000", viewport:{width:1440,height:1000}, trace:"retain-on-failure", screenshot:"only-on-failure"},
  reporter:[["list"],["html",{open:"never"}]],
});
