Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!define APPNAME "资产实验室"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\AssetLab"
Name "${APPNAME}"
OutFile "${OUTFILE}"
VIProductVersion "0.2.1.1"
VIAddVersionKey /LANG=2052 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APPNAME} Windows 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APPVERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APPVERSION}"
VIAddVersionKey /LANG=2052 "CompanyName" "温州氪客科技有限公司"
VIAddVersionKey /LANG=2052 "LegalCopyright" "温州氪客科技有限公司"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\AssetLab"
SetCompressor /SOLID lzma
SetCompressorDictSize 32
Icon "${STAGEDIR}/server/local_client/asset-lab.ico"
UninstallIcon "${STAGEDIR}/server/local_client/asset-lab.ico"
BrandingText "资产实验室 · 安装后，双击桌面图标即可使用"
ShowInstDetails nevershow
ShowUninstDetails show

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "把资产实验室放到你的桌面"
!define MUI_WELCOMEPAGE_TEXT "安装完成后，桌面会自动出现“资产实验室”快捷方式。$\r$\n$\r$\n双击图标，就会在浏览器中打开你的工作台。首次使用，点击“授权 LibTV”连接自己的账号。$\r$\n$\r$\n当前为连接体验版，图像和视频生成暂未开放。"
!define MUI_FINISHPAGE_TITLE "安装完成，开始连接你的账号"
!define MUI_FINISHPAGE_TEXT "桌面的“资产实验室”图标已经准备好。$\r$\n$\r$\n之后每次使用，只需双击图标。"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "立即打开资产实验室"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchAssetLab
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "将卸载资产实验室程序和桌面快捷方式。你保存在本机的项目与账号连接会保留。请先在工作台底部点击“退出本地工作台”。"
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Var InstallMutex

!macro CheckWorkbenchRunning
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\AssetLab.Workbench") p.r0 ?e'
  Pop $1
  ${If} $0 = 0
    MessageBox MB_OK|MB_ICONSTOP "无法检查工作台状态。请关闭工作台后重试。"
    Abort
  ${EndIf}
  ${If} $1 = 183
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK|MB_ICONINFORMATION "资产实验室正在运行。请先在工作台底部点击“退出本地工作台”，再重新打开安装或卸载程序。"
    Abort
  ${EndIf}
  StrCpy $InstallMutex $0
!macroend

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "此安装包适用于 64 位 Windows 电脑。"
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "请在 Windows 10 或更新版本中安装。"
    Abort
  ${EndIf}
  ; Keep installation separate from customer data, even with a supplied /D switch.
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\AssetLab"
  !insertmacro CheckWorkbenchRunning
FunctionEnd

Function un.onInit
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\AssetLab"
  !insertmacro CheckWorkbenchRunning
FunctionEnd

Function LaunchAssetLab
  System::Call 'kernel32::CloseHandle(p $InstallMutex)'
  StrCpy $InstallMutex 0
  SetOutPath "$INSTDIR\versions\${APPVERSION}"
  Exec '"$INSTDIR\versions\${APPVERSION}\runtime\pythonw.exe" "$INSTDIR\versions\${APPVERSION}\server\local_client\launch.py" --frontend "$INSTDIR\versions\${APPVERSION}\public"'
FunctionEnd

Section "安装资产实验室"
  SetShellVarContext current
  SetOutPath "$INSTDIR\versions\${APPVERSION}"
  File /r "${STAGEDIR}/*"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\versions\${APPVERSION}\runtime\pythonw.exe" '"$INSTDIR\versions\${APPVERSION}\server\local_client\launch.py" --frontend "$INSTDIR\versions\${APPVERSION}\public"' "$INSTDIR\versions\${APPVERSION}\server\local_client\asset-lab.ico" 0 SW_SHOWNORMAL "" "打开资产实验室工作台"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\versions\${APPVERSION}\runtime\pythonw.exe" '"$INSTDIR\versions\${APPVERSION}\server\local_client\launch.py" --frontend "$INSTDIR\versions\${APPVERSION}\public"' "$INSTDIR\versions\${APPVERSION}\server\local_client\asset-lab.ico"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\卸载资产实验室.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${APPVERSION}"
  WriteRegStr HKCU "${REGKEY}" "Publisher" "温州氪客科技有限公司"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\versions\${APPVERSION}\server\local_client\asset-lab.ico"
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${REGKEY}" "URLInfoAbout" "https://kk666.best/asset-lab/"
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\卸载资产实验室.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  ; Only the version installed by this uninstaller is removed. Customer data is outside INSTDIR.
  RMDir /r "$INSTDIR\versions\${APPVERSION}"
  RMDir "$INSTDIR\versions"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${REGKEY}"
SectionEnd
