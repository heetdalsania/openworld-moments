; SPDX-License-Identifier: AGPL-3.0-or-later
; Disable NSIS recursive app-data deletion; it must never follow library junctions.
!macro NSIS_HOOK_PREUNINSTALL
  StrCpy $R9 $DeleteAppDataCheckboxState
  StrCpy $DeleteAppDataCheckboxState 0
  ${If} $R9 = 1
  ${AndIf} $UpdateMode <> 1
    IfSilent keep_library
    MessageBox MB_YESNO|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "Delete the local OpenWorld Moments library, projects, transcripts, downloaded models and managed media? External referenced footage is kept. Application preferences are retained. Choose No to keep the library." IDNO keep_library
    !insertmacro CheckIfAppIsRunning "$INSTDIR\${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
    nsExec::ExecToStack '"$INSTDIR\runtime\owm-worker.exe" --purge-library'
    Pop $0
    Pop $1
    ${If} $0 != 0
      MessageBox MB_OK|MB_ICONEXCLAMATION "Library removal could not finish. Retained data can be removed manually after uninstalling."
    ${EndIf}
    keep_library:
  ${EndIf}
!macroend
