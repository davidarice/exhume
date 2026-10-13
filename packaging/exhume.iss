; Windows installer for the Exhume desktop app (Inno Setup 6). The release workflow builds the
; app with PyInstaller into dist\Exhume, then runs:
;     ISCC.exe /DAppVersion=2.1.0 packaging\exhume.iss
; Installs for the current user only: no administrator prompt.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; never change AppId: Windows uses it to recognise upgrades and the uninstaller
AppId={{0ACC6D3C-DD8E-4FC1-95E6-FDF9AF5FBD4B}
AppName=Exhume
AppVersion={#AppVersion}
AppVerName=Exhume {#AppVersion}
AppPublisher=David Rice
AppPublisherURL=https://exhume.app
AppSupportURL=https://github.com/davidarice/exhume/issues
DefaultDirName={autopf}\Exhume
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Exhume-Windows-Setup
SetupIconFile=icons\exhume.ico
UninstallDisplayIcon={app}\Exhume.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Exhume\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; an upgrade replaces the app folder wholesale, so files a newer build no longer has don't linger
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Exhume"; Filename: "{app}\Exhume.exe"
Name: "{autodesktop}\Exhume"; Filename: "{app}\Exhume.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Exhume.exe"; Description: "{cm:LaunchProgram,Exhume}"; Flags: nowait postinstall skipifsilent
