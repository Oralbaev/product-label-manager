; BotaShop Installer — Inno Setup 6 script
; Generated for BotaShop v1.0
;
; Build prerequisite: Inno Setup 6  https://jrsoftware.org/isdl.php
; Input:   dist\BotaShop\*   (produced by build.bat / PyInstaller)
; Output:  dist\BotaShopSetup.exe

#define AppName      "BotaShop"
#define AppVersion   "1.0.0"
#define AppPublisher "BotaShop"
#define AppExeName   "BotaShop.exe"

[Setup]
; Unique application identifier — do NOT change after first release.
; Changing it treats reinstalls as a completely new application.
AppId={{A7C3D9F2-84B1-4E5A-9C6F-2D0B8E1A3F74}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=http://127.0.0.1:8000
AppSupportURL=http://127.0.0.1:8000
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; The database lives in %LOCALAPPDATA%\BotaShop\, not in {app}.
; So the uninstaller never touches user data automatically.
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=dist
OutputBaseFilename=BotaShopSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Require 64-bit Windows
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Do not require admin rights — allows per-user install if needed.
; Change to "yes" if you need a system-wide install for all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; \
  Description: "Создать ярлык на рабочем столе"; \
  GroupDescription: "Дополнительные параметры:"; \
  Flags: checkedonce

[Files]
; Main application bundle
Source: "dist\BotaShop\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
  Comment: "Открыть BotaShop"
; Desktop shortcut (created when user checks the task)
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
  Comment: "Открыть BotaShop"; Tasks: desktopicon

[Run]
; Offer to launch after installation
Filename: "{app}\{#AppExeName}"; \
  Description: "Запустить {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only application files.
; Do NOT list %LOCALAPPDATA%\BotaShop here — that would delete the database!
Type: filesandordirs; Name: "{app}"

[Code]

// Preserve the user database on reinstall / update.
// The database is in %LOCALAPPDATA%\BotaShop\data\,
// which is completely outside the application folder.
// The installer never installs anything there, so it is
// automatically preserved on reinstall and uninstall.

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
