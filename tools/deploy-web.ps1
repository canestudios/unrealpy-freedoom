<#
.SYNOPSIS
Uploads the packaged web build to the repository's GitHub release and starts the Pages workflow that publishes it.

.DESCRIPTION
Run tools\package-web.ps1 first. Needs the GitHub CLI (gh), signed in with rights to the repository. The site is
zipped without the .br copies of files that also have a plain copy: GitHub Pages cannot serve them with their
encoding, so they would only add to the upload.
#>
param(
    [string]$Site = (Join-Path $PSScriptRoot "..\Saved\Web\Wasm"),
    [string]$Tag = "web-build"
)
$ErrorActionPreference = "Stop"
$Site = (Resolve-Path $Site).Path
if (-not (Test-Path (Join-Path $Site "index.html"))) { throw "No web build in $($Site): run tools\package-web.ps1 first." }
if (Get-ChildItem $Site -Recurse -File | Where-Object { $_.FullName -cmatch "\\doom_local(\\|$)|\\DoomLocal(\\|$)" }) {
    throw "Retail Doom data is in $Site. Do not upload it."
}

$zip = Join-Path ([IO.Path]::GetTempPath()) "web.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
$files = Get-ChildItem $Site -Recurse -File | Where-Object {
    -not ($_.Extension -eq ".br" -and (Test-Path ($_.FullName.Substring(0, $_.FullName.Length - 3))))
}
# Forward slashes in the zip's entry names (a zip made with backslashes unpacks into flat names on Linux).
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, "Create")
try {
    foreach ($file in $files) {
        $name = $file.FullName.Substring($Site.Length + 1).Replace("\", "/")
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $name, "Optimal")
    }
}
finally { $archive.Dispose() }
"web.zip: {0:N0} MB, {1} files" -f ((Get-Item $zip).Length / 1MB), $files.Count

gh release view $Tag *> $null
if ($LASTEXITCODE) { gh release create $Tag --title "Web build" --notes "The site GitHub Pages serves (Pages workflow)." }
gh release upload $Tag $zip --clobber
if ($LASTEXITCODE) { throw "Uploading web.zip failed." }
gh workflow run pages.yml -f "tag=$Tag"
"Pages workflow started: gh run watch"
