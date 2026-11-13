<#
  Tự động hoá deploy PDK APEX Web: GitHub + Supabase + Render + Vercel.
  Không chạy trực tiếp file này: dùng deploy.bat hoặc cap-nhat-web.bat ở thư mục gốc,
  hoặc các file .bat trong thư mục deploy\.

  Chạy được trên Windows PowerShell 5.1 (có sẵn trong Windows 10/11).
  Không lưu mật khẩu hay khoá bí mật nào ra đĩa. File deploy\deploy-config.json chỉ chứa
  các địa chỉ công khai (repo GitHub, Render, Vercel) và đã được loại khỏi git.
#>
param(
  [ValidateSet("all", "github", "render", "vercel", "connect", "update", "status")]
  [string]$Step = "all"
)

$ErrorActionPreference = "Continue"   # lệnh ngoài (git, npx) ghi tiến trình ra stderr: tự kiểm tra mã lỗi
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$Root = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $PSScriptRoot "deploy-config.json"
$DefaultRender = "https://pdk-apex-api.onrender.com"
$VercelProject = "pdk-apex-web"
Set-Location $Root

# ------------------------------------------------------------------ tiện ích

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Title([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Green }
function Ok([string]$text) { Say "  [OK] $text" "Green" }
function Warn([string]$text) { Say "  [!] $text" "Yellow" }
function Fail([string]$text) { Say "  [LOI] $text" "Red"; throw $text }

function Ask([string]$question, [string]$default = "") {
  $suffix = if ($default) { " [$default]" } else { "" }
  $answer = Read-Host "$question$suffix"
  if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
  return $answer.Trim()
}

function Confirm([string]$question, [bool]$default = $true) {
  $hint = if ($default) { "Y/n" } else { "y/N" }
  $answer = Read-Host "$question ($hint)"
  if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
  return $answer.Trim().ToLower().StartsWith("y") -or $answer.Trim().ToLower().StartsWith("c")
}

function Pause-Here([string]$text = "Làm xong thì bấm Enter để tiếp tục") { [void](Read-Host "  >> $text") }

function Run([string]$exe, [string[]]$arguments) {
  & $exe @arguments
  if ($LASTEXITCODE -ne 0) { Fail "Lệnh '$exe $($arguments -join ' ')' bị lỗi (mã $LASTEXITCODE)." }
}

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user"
}

function Has([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Need-Tool([string]$cmd, [string]$wingetId, [string]$name, [string]$url) {
  if (Has $cmd) { return }
  Warn "Máy chưa có $name."
  if ((Has "winget") -and (Confirm "Cài $name bằng winget ngay bây giờ?")) {
    & winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
  }
  if (-not (Has $cmd)) {
    Start-Process $url
    Fail "Hãy cài $name ($url), đóng cửa sổ này rồi chạy lại."
  }
  Ok "Đã có $name."
}

function Load-Config {
  if (Test-Path $ConfigPath) {
    try { return Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
  }
  return [pscustomobject]@{ repo = ""; renderUrl = ""; vercelUrl = "" }
}

function Save-Config($cfg) {
  $json = $cfg | ConvertTo-Json
  [IO.File]::WriteAllText($ConfigPath, $json, (New-Object Text.UTF8Encoding $false))
}

function Set-Conf($cfg, [string]$key, [string]$value) {
  $cfg | Add-Member -NotePropertyName $key -NotePropertyValue $value -Force
  Save-Config $cfg
}

function Normalize-Url([string]$url) {
  $u = $url.Trim().TrimEnd("/")
  if ($u -and -not $u.StartsWith("http")) { $u = "https://$u" }
  return $u
}

function Repo-WebUrl([string]$remote) {
  # git@github.com:a/b.git hoặc https://github.com/a/b.git -> https://github.com/a/b
  $r = $remote.Trim()
  if ($r -match "^git@github\.com:(.+?)(\.git)?$") { return "https://github.com/$($Matches[1])" }
  if ($r -match "^https://(?:[^@/]+@)?github\.com/(.+?)(\.git)?/?$") { return "https://github.com/$($Matches[1])" }
  return $r
}

function Wait-Health([string]$baseUrl, [int]$minutes, [switch]$DbCheck) {
  $url = "$baseUrl/api/health"
  if ($DbCheck) { $url += "?db_check=true" }
  $deadline = (Get-Date).AddMinutes($minutes)
  Say "  Đang chờ $url trả lời (tối đa $minutes phút)..."
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-RestMethod -Uri $url -TimeoutSec 60 -UseBasicParsing
      if ($r.status -eq "ok") { Ok "Máy chủ đã chạy (apexmark $($r.apexmark_version))."; return $true }
    } catch {
      $code = $null
      if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
      $msg = if ($code) { "mã $code" } else { "chưa kết nối được" }
      Say "    ...chưa sẵn sàng ($msg), thử lại sau 15 giây" "DarkGray"
    }
    Start-Sleep -Seconds 15
  }
  return $false
}

function Git-Commit-All([string]$message) {
  Run git @("add", "-A")
  & git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    Run git @("commit", "-m", $message)
    Ok "Đã tạo commit: $message"
  } else {
    Ok "Không có thay đổi mới để commit."
  }
}

function Git-Push {
  $branch = (& git branch --show-current).Trim()
  if (-not $branch) { $branch = "main" }
  Run git @("push", "-u", "origin", $branch)
  Ok "Đã đẩy nhánh $branch lên GitHub."
}

function Ensure-GitIdentity {
  $name = (& git config user.name)
  $email = (& git config user.email)
  if (-not $name) {
    $name = Ask "Tên hiển thị trên commit (git user.name)" "PDK"
    Run git @("config", "--global", "user.name", $name)
  }
  if (-not $email) {
    $email = Ask "Email trên commit (git user.email, có thể dùng email noreply của GitHub)"
    if (-not $email) { Fail "Cần một email cho git." }
    Run git @("config", "--global", "user.email", $email)
  }
}

# ------------------------------------------------------------------ bước 1: GitHub

function Step-GitHub($cfg) {
  Title "BƯỚC 1/4 · GitHub: đưa mã nguồn lên"
  Need-Tool "git" "Git.Git" "Git" "https://git-scm.com/download/win"

  # File cũ từ bản dùng Docker và file không còn dùng: không đưa lên GitHub.
  $stale = @("Dockerfile", "docker-compose.yml", ".dockerignore", "frontend\public\favicon.svg") |
    Where-Object { Test-Path (Join-Path $Root $_) }
  if ($stale) {
    Warn "Còn file cũ không dùng nữa: $($stale -join ', ')"
    if (Confirm "Xoá các file này?") {
      $stale | ForEach-Object { Remove-Item (Join-Path $Root $_) -Force }
      Ok "Đã xoá."
    }
  }

  if (-not (Test-Path (Join-Path $Root ".git"))) {
    Run git @("init", "-b", "main")
    Ok "Đã tạo kho git."
  }
  Ensure-GitIdentity

  # Chặn lỡ tay đưa bí mật lên GitHub.
  foreach ($f in @("backend\.env", "frontend\.env")) {
    if (Test-Path (Join-Path $Root $f)) {
      & git check-ignore -q $f
      if ($LASTEXITCODE -ne 0) { Fail "$f chứa cấu hình riêng nhưng không bị .gitignore loại ra. Dừng lại để tránh lộ bí mật." }
    }
  }

  Git-Commit-All "Chuẩn bị deploy PDK APEX Web"

  $remote = (& git remote get-url origin 2>$null)
  if (-not $remote) {
    $useGh = $false
    if (Has "gh") { $useGh = $true }
    elseif ((Has "winget") -and (Confirm "Cài GitHub CLI để tự tạo repo (khuyên dùng)?")) {
      & winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
      Refresh-Path
      $useGh = Has "gh"
    }

    if ($useGh) {
      & gh auth status 2>$null | Out-Null
      if ($LASTEXITCODE -ne 0) {
        Say "  Trình duyệt sẽ mở để bạn đăng nhập GitHub."
        Run gh @("auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web")
      }
      $name = Ask "Tên repo GitHub" "pdk-apex-web"
      $vis = if (Confirm "Để repo ở chế độ riêng tư (private)?") { "--private" } else { "--public" }
      Run gh @("repo", "create", $name, $vis, "--source", ".", "--remote", "origin", "--push")
      Ok "Đã tạo repo và đẩy mã lên."
    } else {
      Start-Process "https://github.com/new"
      Say "  Trên trang vừa mở: đặt tên repo, KHÔNG tích README/.gitignore, bấm Create repository."
      $url = Ask "Dán địa chỉ repo (ví dụ https://github.com/ten-ban/pdk-apex-web)"
      if (-not $url) { Fail "Cần địa chỉ repo." }
      Run git @("remote", "add", "origin", ((Repo-WebUrl $url) + ".git"))
      Say "  Nếu Windows hỏi đăng nhập GitHub, hãy đăng nhập trong cửa sổ hiện ra."
      Git-Push
    }
  } else {
    Git-Push
  }

  $web = Repo-WebUrl (& git remote get-url origin)
  Set-Conf $cfg "repo" $web
  Ok "Repo: $web"
}

# ------------------------------------------------------------------ bước 2: Supabase + Render

function Step-Render($cfg) {
  Title "BƯỚC 2/4 · Supabase (dữ liệu) và Render (backend)"
  if (-not $cfg.repo) { Fail "Chưa có repo GitHub. Hãy chạy bước 1 trước." }

  Say ""
  Say "  2a. Supabase: trình duyệt sẽ mở trang tạo dự án."
  Say "      - Region: Southeast Asia (Singapore). Database password: bấm Generate và CHÉP LẠI."
  Say "      - Tạo xong, chép 3 giá trị vào Notepad (chi tiết trong DEPLOY.md, bước 2):"
  Say "          SUPABASE_URL          Project Settings > Data API > Project URL"
  Say "          SUPABASE_SERVICE_KEY  Project Settings > API Keys > service_role (secret)"
  Say "          DATABASE_URL          nút Connect > Session pooler (thay [YOUR-PASSWORD])"
  if (Confirm "Mở Supabase ngay?") { Start-Process "https://supabase.com/dashboard/projects" }
  Pause-Here "Có đủ 3 giá trị rồi thì bấm Enter"

  Say ""
  Say "  2b. Render: trình duyệt sẽ mở trang tạo dịch vụ từ file render.yaml của repo."
  Say "      - Đăng nhập Render bằng GitHub, cho phép Render đọc repo nếu được hỏi."
  Say "      - Dán DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY. Để TRỐNG TRUSTED_ORIGINS."
  Say "      - Bấm Apply / Deploy Blueprint. Lần build đầu mất 5 đến 10 phút."
  Start-Process ("https://render.com/deploy?repo=" + $cfg.repo)
  Pause-Here "Bấm Apply xong thì bấm Enter"

  $default = if ($cfg.renderUrl) { $cfg.renderUrl } else { $DefaultRender }
  $render = Normalize-Url (Ask "Địa chỉ dịch vụ trên Render (xem ở đầu trang dịch vụ)" $default)
  Set-Conf $cfg "renderUrl" $render

  if (Wait-Health $render 20 -DbCheck) {
    Ok "Backend chạy và đã nối được Supabase."
  } else {
    Warn "Backend chưa trả lời. Mở trang Render > Logs để xem lỗi. Hay gặp nhất: DATABASE_URL sai mật khẩu"
    Warn "hoặc dùng Direct connection thay vì Session pooler. Sửa xong chạy lại bước 2."
    throw "Backend chưa sẵn sàng."
  }
}

# ------------------------------------------------------------------ bước 3: Vercel

function Set-VercelBackend([string]$render) {
  $path = Join-Path $Root "frontend\vercel.json"
  $text = [IO.File]::ReadAllText($path)
  $new = [regex]::Replace($text, '"destination":\s*"https?://[^"]*/api/:path\*"', ('"destination": "' + $render + '/api/:path*"'))
  if ($new -ne $text) {
    [IO.File]::WriteAllText($path, $new, (New-Object Text.UTF8Encoding $false))
    Ok "Đã trỏ frontend/vercel.json tới $render"
    return $true
  }
  Ok "frontend/vercel.json đã trỏ đúng $render"
  return $false
}

function Vercel([string[]]$arguments) {
  Push-Location (Join-Path $Root "frontend")
  try {
    $out = & npx --yes vercel@latest @arguments
    if ($LASTEXITCODE -ne 0) { Fail "Vercel CLI báo lỗi khi chạy: vercel $($arguments -join ' ')" }
    return $out
  } finally { Pop-Location }
}

function Ensure-VercelLogin {
  Push-Location (Join-Path $Root "frontend")
  try {
    & npx --yes vercel@latest whoami 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Say "  Đăng nhập Vercel (chọn Continue with GitHub trong trình duyệt)."
      & npx --yes vercel@latest login
      if ($LASTEXITCODE -ne 0) { Fail "Chưa đăng nhập được Vercel." }
    }
  } finally { Pop-Location }
}

function Deploy-Vercel($cfg) {
  Ensure-VercelLogin
  if (-not (Test-Path (Join-Path $Root "frontend\.vercel\project.json"))) {
    [void](Vercel @("link", "--yes", "--project", $VercelProject))
  }
  Say "  Đang build và đưa giao diện lên Vercel (khoảng 1 đến 2 phút)..."
  $out = Vercel @("deploy", "--prod", "--yes")
  $deployUrl = ($out | Where-Object { $_ -match "^https://" } | Select-Object -Last 1)
  if ($deployUrl) { Ok "Bản vừa deploy: $deployUrl" }
}

function Step-Vercel($cfg) {
  Title "BƯỚC 3/4 · Vercel (giao diện)"
  if (-not $cfg.renderUrl) { Fail "Chưa có địa chỉ Render. Hãy chạy bước 2 trước." }
  Need-Tool "node" "OpenJS.NodeJS.LTS" "Node.js" "https://nodejs.org/"

  if (Set-VercelBackend $cfg.renderUrl) {
    Git-Commit-All "Trỏ Vercel tới backend $($cfg.renderUrl)"
    if ($cfg.repo) { Git-Push }
  }
  Deploy-Vercel $cfg

  $default = if ($cfg.vercelUrl) { $cfg.vercelUrl } else { "https://$VercelProject.vercel.app" }
  Say "  Địa chỉ chính thức nằm ở Vercel > dự án $VercelProject > Domains."
  $vercel = Normalize-Url (Ask "Địa chỉ chính thức của trang" $default)
  Set-Conf $cfg "vercelUrl" $vercel
  Ok "Giao diện: $vercel"
}

# ------------------------------------------------------------------ bước 4: nối hai bên

function Set-RenderTrustedOrigin($cfg) {
  Say ""
  Say "  Cần đặt TRUSTED_ORIGINS = $($cfg.vercelUrl) trên Render để đăng nhập và lưu lịch sử hoạt động."
  Say "  Cách tự động cần Render API key (Render > Account Settings > API Keys > Create API Key)."
  if (-not (Confirm "Dùng API key để script tự đặt?")) { return $false }

  $secure = Read-Host "  Dán Render API key (không hiện ra màn hình, không được lưu lại)" -AsSecureString
  $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
  if (-not $key) { return $false }
  $headers = @{ Authorization = "Bearer $key"; Accept = "application/json" }
  try {
    $list = Invoke-RestMethod -Uri "https://api.render.com/v1/services?limit=50" -Headers $headers -TimeoutSec 30
    $host_ = ([Uri]$cfg.renderUrl).Host
    $svc = $list | ForEach-Object { $_.service } | Where-Object {
      ($_.serviceDetails.url -and ([Uri]$_.serviceDetails.url).Host -eq $host_) -or $_.name -eq "pdk-apex-api"
    } | Select-Object -First 1
    if (-not $svc) { Warn "Không tìm thấy dịch vụ $host_ trong tài khoản Render này."; return $false }

    $body = @{ value = $cfg.vercelUrl } | ConvertTo-Json
    Invoke-RestMethod -Method Put -Uri "https://api.render.com/v1/services/$($svc.id)/env-vars/TRUSTED_ORIGINS" `
      -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 30 | Out-Null
    Invoke-RestMethod -Method Post -Uri "https://api.render.com/v1/services/$($svc.id)/deploys" `
      -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 30 | Out-Null
    Ok "Đã đặt TRUSTED_ORIGINS và cho Render khởi động lại."
    return $true
  } catch {
    Warn "Gọi Render API không thành công: $($_.Exception.Message)"
    return $false
  } finally {
    $key = $null
  }
}

function Step-Connect($cfg) {
  Title "BƯỚC 4/4 · Nối giao diện với backend"
  if (-not $cfg.vercelUrl -or -not $cfg.renderUrl) { Fail "Thiếu địa chỉ Render hoặc Vercel. Hãy chạy bước 2 và 3." }

  if (-not (Set-RenderTrustedOrigin $cfg)) {
    Start-Process "https://dashboard.render.com"
    Say "  Làm tay: mở dịch vụ pdk-apex-api > Environment > TRUSTED_ORIGINS = $($cfg.vercelUrl) > Save."
    Pause-Here
  }

  # Biến cho lịch ping hằng ngày (giữ Supabase không bị tạm dừng).
  if (Has "gh") {
    & gh variable set SITE_URL --body $cfg.vercelUrl
    if ($LASTEXITCODE -eq 0) { Ok "Đã đặt biến SITE_URL trên GitHub cho lịch ping hằng ngày." }
  } else {
    Warn "Chưa có GitHub CLI: hãy tự đặt biến SITE_URL = $($cfg.vercelUrl) (xem DEPLOY.md, bước 6)."
  }

  Say "  Kiểm tra trang qua Vercel (Render có thể mất vài phút để khởi động lại)..."
  if (Wait-Health $cfg.vercelUrl 10 -DbCheck) {
    Title "XONG"
    Ok "Web: $($cfg.vercelUrl)"
    Say "  Thử ngay: giấu tin, đăng ký tài khoản, giấu tin lần nữa, rồi mở tab Lịch sử."
    Start-Process $cfg.vercelUrl
  } else {
    Warn "Trang chưa gọi được backend qua Vercel. Kiểm tra frontend/vercel.json và trang Render > Logs."
  }
}

# ------------------------------------------------------------------ cập nhật về sau

function Step-Update($cfg) {
  Title "CẬP NHẬT WEB"
  if (-not $cfg.repo) { Fail "Chưa deploy lần nào. Hãy chạy deploy.bat trước." }
  $msg = Ask "Mô tả ngắn thay đổi" ("Cập nhật " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
  if ($cfg.renderUrl) { [void](Set-VercelBackend $cfg.renderUrl) }
  Git-Commit-All $msg
  Git-Push
  Ok "Render sẽ tự build lại backend từ GitHub trong vài phút."
  if ($cfg.vercelUrl) {
    Need-Tool "node" "OpenJS.NodeJS.LTS" "Node.js" "https://nodejs.org/"
    Deploy-Vercel $cfg
  }
  if ($cfg.renderUrl) {
    Say "  Chờ Render build xong (thường 3 đến 8 phút)..."
    Start-Sleep -Seconds 60
    [void](Wait-Health $cfg.renderUrl 15)
  }
  Title "XONG"
  if ($cfg.vercelUrl) { Ok "Web: $($cfg.vercelUrl)" }
}

function Step-Status($cfg) {
  Title "TRẠNG THÁI"
  Say "  Repo GitHub : $(if ($cfg.repo) { $cfg.repo } else { '(chưa có)' })"
  Say "  Render      : $(if ($cfg.renderUrl) { $cfg.renderUrl } else { '(chưa có)' })"
  Say "  Vercel      : $(if ($cfg.vercelUrl) { $cfg.vercelUrl } else { '(chưa có)' })"
  if ($cfg.vercelUrl) { [void](Wait-Health $cfg.vercelUrl 3 -DbCheck) }
  elseif ($cfg.renderUrl) { [void](Wait-Health $cfg.renderUrl 3 -DbCheck) }
}

# ------------------------------------------------------------------ chạy

$cfg = Load-Config
try {
  switch ($Step) {
    "github"  { Step-GitHub $cfg }
    "render"  { Step-Render $cfg }
    "vercel"  { Step-Vercel $cfg }
    "connect" { Step-Connect $cfg }
    "update"  { Step-Update $cfg }
    "status"  { Step-Status $cfg }
    "all" {
      Say "Deploy PDK APEX Web: GitHub -> Supabase + Render -> Vercel -> nối lại." "Cyan"
      Say "Mỗi bước đã làm xong có thể bỏ qua khi chạy lại." "Cyan"
      if (-not $cfg.repo -or (Confirm "Bước 1 (GitHub) đã làm rồi ($($cfg.repo)). Làm lại?" $false)) { Step-GitHub $cfg }
      if (-not $cfg.renderUrl -or (Confirm "Bước 2 (Render) đã làm rồi ($($cfg.renderUrl)). Làm lại?" $false)) { Step-Render $cfg }
      if (-not $cfg.vercelUrl -or (Confirm "Bước 3 (Vercel) đã làm rồi ($($cfg.vercelUrl)). Làm lại?" $false)) { Step-Vercel $cfg }
      Step-Connect $cfg
    }
  }
  exit 0
} catch {
  Say ""
  Say "Dừng lại: $($_.Exception.Message)" "Red"
  Say "Sửa lỗi rồi chạy lại; các bước đã xong sẽ được hỏi để bỏ qua." "Yellow"
  exit 1
}
