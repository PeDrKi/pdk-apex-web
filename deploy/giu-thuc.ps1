<#
  Bật/tắt hai việc "giữ thức" của PDK APEX Web, đều chạy bằng GitHub Actions (không cần máy bạn bật):
    - Render   : gọi backend 10 phút một lần để Render không ngủ   (.github/workflows/render-awake.yml)
    - Supabase : gọi web kèm cơ sở dữ liệu mỗi ngày một lần để dự án không bị tạm dừng (keepalive.yml)

  Không chạy trực tiếp file này: bấm đúp giu-thuc.bat ở thư mục gốc.
  Cần GitHub CLI (gh) đã đăng nhập. Script không lưu mật khẩu hay khoá nào.

  Chạy thẳng không qua menu:  giu-thuc.bat render-on | render-off | supabase-on | supabase-off | status
#>
param(
  [ValidateSet("menu", "status", "render-on", "render-off", "supabase-on", "supabase-off")]
  [string]$Action = "menu"
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $PSScriptRoot "deploy-config.json"
$DefaultRender = "https://pdk-apex-api.onrender.com"
Set-Location $Root

$Jobs = @{
  render   = @{ file = "render-awake.yml"; name = "Render không ngủ";        var = "RENDER_URL" }
  supabase = @{ file = "keepalive.yml";    name = "Supabase không tạm dừng"; var = "SITE_URL" }
}

$RenderWorkflow = @'
# Goi backend 10 phut mot lan de Render goi free khong ngu (Render ngu sau 15 phut khong ai dung).
# Bat/tat bang giu-thuc.bat. Can bien RENDER_URL trong Settings > Secrets and variables > Actions > Variables.
name: render-awake
on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:
jobs:
  ping:
    runs-on: ubuntu-latest
    timeout-minutes: 4
    if: ${{ vars.RENDER_URL != '' }}
    steps:
      - name: Ping Render
        run: curl -fsS --max-time 100 --retry 2 --retry-delay 10 "${{ vars.RENDER_URL }}/api/health"
'@

$SupabaseWorkflow = @'
# Goi web moi ngay mot lan de du an Supabase goi free khong bi tam dung vi "khong hoat dong".
# Bat/tat bang giu-thuc.bat. Can bien SITE_URL trong Settings > Secrets and variables > Actions > Variables.
name: keepalive
on:
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:
jobs:
  ping:
    runs-on: ubuntu-latest
    timeout-minutes: 6
    if: ${{ vars.SITE_URL != '' }}
    steps:
      - name: Ping web va co so du lieu
        run: |
          for i in 1 2 3 4 5 6; do
            if curl -fsS --max-time 90 "${{ vars.SITE_URL }}/api/health?db_check=true"; then exit 0; fi
            echo "Chua tra loi, thu lai sau 30 giay"; sleep 30
          done
          exit 1
'@

# ------------------------------------------------------------------ tiện ích

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Title([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Green }
function Ok([string]$text) { Say "  [OK] $text" "Green" }
function Warn([string]$text) { Say "  [!] $text" "Yellow" }
function Fail([string]$text) { throw $text }
function Has([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Confirm([string]$question, [bool]$default = $true) {
  $hint = if ($default) { "Y/n" } else { "y/N" }
  $answer = Read-Host "$question ($hint)"
  if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
  return $answer.Trim().ToLower().StartsWith("y") -or $answer.Trim().ToLower().StartsWith("c")
}

function Ask([string]$question, [string]$default = "") {
  $suffix = if ($default) { " [$default]" } else { "" }
  $answer = Read-Host "$question$suffix"
  if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
  return $answer.Trim().TrimEnd("/")
}

function Ensure-Tools {
  if (-not (Has "git")) { Fail "Máy chưa có Git. Hãy chạy deploy.bat trước, hoặc cài từ https://git-scm.com" }
  if (-not (Has "gh")) {
    Warn "Máy chưa có GitHub CLI (gh), script cần nó để bật/tắt."
    if ((Has "winget") -and (Confirm "Cài GitHub CLI bằng winget ngay bây giờ?")) {
      & winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
      $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    }
    if (-not (Has "gh")) { Fail "Hãy cài GitHub CLI từ https://cli.github.com rồi chạy lại." }
  }
  & gh auth status 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Say "  Cần đăng nhập GitHub một lần. Trình duyệt sẽ mở, làm theo hướng dẫn trên màn hình."
    & gh auth login --hostname github.com --git-protocol https --web --scopes "repo,workflow"
    if ($LASTEXITCODE -ne 0) { Fail "Chưa đăng nhập được GitHub." }
  }
}

function Get-Repo {
  $json = & gh repo view --json nameWithOwner,visibility 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $json) {
    Fail "Thư mục này chưa nối với repo GitHub nào. Hãy chạy deploy.bat (bước 1) trước."
  }
  return ($json | Out-String | ConvertFrom-Json)
}

function Get-States {
  # Trả về bảng: tên file workflow -> trạng thái (active, disabled_manually, disabled_inactivity...)
  $map = @{}
  $json = & gh api "repos/{owner}/{repo}/actions/workflows?per_page=100" 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $json) { return $map }
  foreach ($w in ($json | Out-String | ConvertFrom-Json).workflows) {
    $map[(Split-Path $w.path -Leaf)] = $w.state
  }
  return $map
}

function State-Text([string]$state) {
  if (-not $state) { return "CHƯA CÀI" }
  if ($state -eq "active") { return "ĐANG BẬT" }
  if ($state -eq "disabled_inactivity") { return "TẮT (GitHub tự tắt vì repo 60 ngày không đổi)" }
  return "ĐANG TẮT"
}

function Show-Status {
  $states = Get-States
  foreach ($key in @("render", "supabase")) {
    $job = $Jobs[$key]
    $text = State-Text $states[$job.file]
    $color = if ($states[$job.file] -eq "active") { "Green" } else { "Yellow" }
    Say ("  {0,-26} {1}" -f $job.name, $text) $color
  }
  return $states
}

function Load-Url([string]$key) {
  if (Test-Path $ConfigPath) {
    try {
      $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($cfg.$key) { return ([string]$cfg.$key).TrimEnd("/") }
    } catch { }
  }
  return ""
}

function Ensure-Variable([string]$name) {
  # Workflow đọc địa chỉ từ biến của repo; thiếu biến thì nó bỏ qua không chạy.
  $current = & gh variable get $name 2>$null
  if ($LASTEXITCODE -eq 0 -and $current) { Ok "$name = $($current | Out-String | ForEach-Object { $_.Trim() })"; return }
  if ($name -eq "RENDER_URL") {
    $guess = Load-Url "renderUrl"
    if (-not $guess) { $guess = $DefaultRender }
    $value = Ask "Địa chỉ backend trên Render" $guess
  } else {
    $value = Ask "Địa chỉ web trên Vercel (ví dụ https://pdk-apex-web.vercel.app)" (Load-Url "vercelUrl")
  }
  if (-not $value) { Fail "Cần địa chỉ để đặt biến $name." }
  if (-not $value.StartsWith("http")) { $value = "https://$value" }
  & gh variable set $name --body $value
  if ($LASTEXITCODE -ne 0) { Fail "Không đặt được biến $name trên GitHub." }
  Ok "Đã đặt $name = $value"
}

function Install-Workflow([string]$file, [string]$content) {
  # Tạo file workflow, commit riêng file đó và đẩy lên GitHub.
  $dir = Join-Path $Root ".github\workflows"
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $path = Join-Path $dir $file
  [IO.File]::WriteAllText($path, ($content -replace "`r`n", "`n") + "`n", (New-Object Text.UTF8Encoding $false))
  $rel = ".github/workflows/$file"
  & git add -- $rel
  & git commit -m "Them workflow $file" -- $rel | Out-Null
  $branch = (& git rev-parse --abbrev-ref HEAD | Out-String).Trim()
  & git pull --rebase --autostash origin $branch
  if ($LASTEXITCODE -ne 0) { Fail "git pull bị lỗi. Hãy chạy 'git status' để xem, sửa xong rồi chạy lại." }
  & git push origin $branch
  if ($LASTEXITCODE -ne 0) {
    Warn "Đẩy lên GitHub bị từ chối. Nếu lỗi nhắc tới 'workflow scope', hãy chạy lệnh sau rồi chạy lại script:"
    Say "      gh auth refresh -h github.com -s workflow"
    Fail "Chưa đẩy được file $file lên GitHub."
  }
  Ok "Đã đưa $file lên GitHub."
  # GitHub cần vài giây để nhận ra workflow mới.
  for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 3
    if ((Get-States).ContainsKey($file)) { return }
  }
  Warn "GitHub chưa hiện workflow $file. Đợi một phút rồi chạy lại script để kiểm tra."
}

function Turn-On([string]$key, $repo) {
  $job = $Jobs[$key]
  Title "Bật: $($job.name)"
  if ($key -eq "render" -and $repo.visibility -ne "PUBLIC") {
    Warn "Repo đang ở chế độ riêng tư (private)."
    Say  "      Gọi 10 phút một lần là khoảng 4.300 lượt mỗi tháng, mỗi lượt tính tròn 1 phút,"
    Say  "      trong khi repo private chỉ có 2.000 phút GitHub Actions miễn phí mỗi tháng."
    Say  "      Hết phút miễn phí thì mọi workflow (kể cả giữ Supabase) dừng tới đầu tháng sau."
    Say  "      Repo công khai (public) thì không bị tính phút. Cách khác: dùng UptimeRobot (miễn phí)."
    if (-not (Confirm "Vẫn bật cho repo private?" $false)) { Say "  Đã bỏ qua."; return }
  }
  Ensure-Variable $job.var
  $states = Get-States
  if (-not $states.ContainsKey($job.file)) {
    $content = if ($key -eq "render") { $RenderWorkflow } else { $SupabaseWorkflow }
    Install-Workflow $job.file $content
    $states = Get-States
  }
  if ($states[$job.file] -ne "active") {
    & gh workflow enable $job.file
    if ($LASTEXITCODE -ne 0) { Fail "Không bật được workflow $($job.file)." }
  }
  Ok "$($job.name): ĐANG BẬT"
  if (Confirm "Chạy thử một lượt ngay bây giờ?") {
    & gh workflow run $job.file
    if ($LASTEXITCODE -eq 0) { Say "  Đã gửi lệnh chạy. Xem kết quả ở tab Actions của repo, hoặc gõ: gh run list --workflow $($job.file) --limit 1" }
  }
  if ($key -eq "render") {
    Say "  Lưu ý: GitHub hay chạy trễ vài phút khi đông, nên thỉnh thoảng Render vẫn có thể ngủ một lúc."
  }
}

function Turn-Off([string]$key) {
  $job = $Jobs[$key]
  Title "Tắt: $($job.name)"
  $states = Get-States
  if (-not $states.ContainsKey($job.file)) { Ok "Chưa từng cài, không có gì để tắt."; return }
  if ($states[$job.file] -eq "active") {
    & gh workflow disable $job.file
    if ($LASTEXITCODE -ne 0) { Fail "Không tắt được workflow $($job.file)." }
  }
  Ok "$($job.name): ĐANG TẮT"
  if ($key -eq "render") { Say "  Render sẽ ngủ sau khoảng 15 phút không ai dùng; lượt vào đầu tiên phải chờ khoảng một phút." }
  else { Say "  Supabase sẽ tạm dừng dự án nếu khoảng một tuần không có ai dùng web. Khi đó vào Supabase bấm Restore project." }
}

function Toggle([string]$key, $repo) {
  $states = Get-States
  if ($states[$Jobs[$key].file] -eq "active") { Turn-Off $key } else { Turn-On $key $repo }
}

# ------------------------------------------------------------------ chạy

try {
  Title "GIỮ THỨC: RENDER VÀ SUPABASE"
  Ensure-Tools
  $repo = Get-Repo
  Say "  Repo: $($repo.nameWithOwner) ($($repo.visibility.ToLower()))"

  switch ($Action) {
    "status"       { [void](Show-Status) }
    "render-on"    { Turn-On "render" $repo }
    "render-off"   { Turn-Off "render" }
    "supabase-on"  { Turn-On "supabase" $repo }
    "supabase-off" { Turn-Off "supabase" }
    default {
      while ($true) {
        Write-Host ""
        [void](Show-Status)
        Write-Host ""
        Say "  1. Bật/tắt: Render không ngủ"
        Say "  2. Bật/tắt: Supabase không tạm dừng"
        Say "  3. Bật cả hai"
        Say "  4. Tắt cả hai"
        Say "  0. Thoát"
        $choice = Read-Host "Chọn"
        switch ($choice.Trim()) {
          "1" { Toggle "render" $repo }
          "2" { Toggle "supabase" $repo }
          "3" { Turn-On "supabase" $repo; Turn-On "render" $repo }
          "4" { Turn-Off "render"; Turn-Off "supabase" }
          "0" { exit 0 }
          ""  { exit 0 }
          default { Warn "Hãy nhập 0, 1, 2, 3 hoặc 4." }
        }
      }
    }
  }
} catch {
  Write-Host ""
  Say "  [LOI] $($_.Exception.Message)" "Red"
  exit 1
}
