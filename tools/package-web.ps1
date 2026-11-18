<#
.SYNOPSIS
Packages the web (Wasm) build of Doom on UnrealPy into <Output>\Wasm, ready to upload as a static site.

.DESCRIPTION
Needs Unreal Engine 5.9 with the Wasm platform, the Emscripten SDK the engine asks for (README.md, Web build),
UnrealPy built with its web Python, and the Freedoom data set imported. Only Freedoom is packaged: the retail
data set is never staged, and the script fails if any of it reaches the output.
#>
param(
    [string]$Engine = "C:\Program Files\Epic Games\UE_5.9",
    [string]$Output = (Join-Path $PSScriptRoot "..\Saved\Web"),
    [ValidateSet("Shipping", "Development")] [string]$Config = "Shipping"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$project = Join-Path $root "UnrealPyDoom.uproject"
$editor = Join-Path $Engine "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$uat = Join-Path $Engine "Engine\Build\BatchFiles\RunUAT.bat"

if (-not (Test-Path (Join-Path $root "Python\doom_local_freedoom1\manifest.json"))) {
    throw "The Freedoom data set is not imported (README.md, Import with DOOM_IWAD=freedoom1)."
}

# The editor (the metadata step below and the cook run it) needs the project's and the plugins' editor modules.
Push-Location (Join-Path $Engine "Engine\Build\BatchFiles")
try { & .\Build.bat UnrealPyDoomEditor Win64 Development "-Project=$project" -WaitMutex -NoHotReload; if ($LASTEXITCODE) { throw "Building the editor failed." } }
finally { Pop-Location }

# The packages the game needs at runtime, without the development tools of .venv. UnrealPy stages this
# environment instead of .venv; on the web only its pure-Python packages are kept (NumPy is built in).
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $root "Intermediate\UnrealPy\uv\uv.exe" }
$env:UV_PROJECT_ENVIRONMENT = Join-Path $root "Intermediate\UnrealPy\RuntimeVenv"
try { & $uv sync --project $root --no-dev --frozen --quiet; if ($LASTEXITCODE) { throw "uv sync failed" } }
finally { Remove-Item Env:UV_PROJECT_ENVIRONMENT }

# What cooking strips from the engine's functions (parameter defaults), written by the editor; the build stages it.
& $editor $project -nullrhi -unattended -nosplash -nopause "-UnrealPyRun=ue._packaging:write_metadata" | Out-Null
if ($LASTEXITCODE) { throw "Writing the function metadata failed (Saved\Logs)." }

# The build lists the files to stage when it makes the target's makefile: drop it so the list is taken now.
Get-ChildItem (Join-Path $root "Intermediate\Build") -Recurse -Filter Makefile.bin -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "\\Wasm\\" } | Remove-Item

# Python/ is staged except the retail data set and what the import alone reads (the game uses the imported
# assets): the maps' JSON, the names and the textures stay (the game reads the sky textures' top colour; the
# others cost hosting space only, as the page downloads a file when it is first read).
$env:UNREALPY_STAGE_EXCLUDE = "doom_local;doom_local_freedoom1/sounds;doom_local_freedoom1/sprites;doom_local_freedoom1/saves"
try {
    & $uat BuildCookRun "-project=$project" -platform=Wasm "-clientconfig=$Config" -build -cook -stage -pak -iostore `
        -package -archive "-archivedirectory=$Output" -nop4 -utf8output -unattended
    if ($LASTEXITCODE) { throw "BuildCookRun failed ($LASTEXITCODE); see the UAT log above." }
}
finally { Remove-Item Env:UNREALPY_STAGE_EXCLUDE }

$site = Join-Path $Output "Wasm"
# Cooked assets sit inside the containers, so the cook output is checked as well as the staged loose files.
# Case-sensitive: FreedoomLocal must not match DoomLocal.
$cooked = Join-Path $root "Saved\Cooked\Wasm"
$retail = @($site, $cooked) | Where-Object { Test-Path $_ } | ForEach-Object { Get-ChildItem $_ -Recurse } |
    Where-Object { $_.FullName -cmatch "\\doom_local(\\|$)|\\DoomLocal(\\|$)" }
if ($retail) { throw "Retail Doom data reached the build: $($retail[0].FullName). Do not upload it." }
$size = (Get-ChildItem $site -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
"Web build in $site ({0:N0} MB). Test it with $(Join-Path $Output 'Play_UnrealPyDoom.bat')." -f $size
