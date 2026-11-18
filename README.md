# new_win_razor: setup and run

These steps install XClient on a Windows host, without MA, and run the Windows XClient tests
against HXSim. The tests cover audits (memory audits included), Eventor collection and IOC
alerts. Known failing audit tests are skipped automatically (`KNOWN_FAILURES` in `conftest.py`,
plus the tests marked `defect` or `broken`).

## 1. Prepare the host

1. Use a Windows x64 machine (physical or VM) that you can reboot. Run the tests on the console
   or over a VM console, not over RDP: one IOC test releases and renews the network adapter.
2. Make sure that:
   - neither XClient nor McAfee Agent (MA) is installed;
   - no reboot is pending (reboot first if Windows Update or an uninstall asked for one);
   - you can open a command prompt **as Administrator**.
3. The host needs network access to:
   - `artifactory.trellix.com`
   - `artifactory.eng.fireeye.com`
   - `github.com`
   - `github.trellix.com`
4. Have about 30 GB of free disk space on `C:`. Tools are installed into `C:\nwr`, and the build
   and test results need room.

## 2. Get the credentials

| Variable | Required | What it is |
|---|---|---|
| `ARTIFACTORY_USER` | yes | Your Artifactory user name (e.g. `first.last@trellix.com`) |
| `ARTIFACTORY_TOKEN` | yes | Your Artifactory API token / identity token |
| `XCLIENT_GITHUB_TOKEN` | yes, unless Git Credential Manager is signed in to github.trellix.com | A github.trellix.com personal access token that can read `unified-agent/XClient` and the ma-sdk-fake repo |
| `MA_SDK_FAKE_REPO` | yes, to build the fake-MA XClient | The git URL of the ma-sdk-fake repo, e.g. `https://github.trellix.com/<owner>/ma-sdk-fake.git` |
| `MA_SDK_FAKE_BRANCH` | no | The ma-sdk-fake branch to build (default `main`) |
| `NWR_ROOT` | no | Where tools are installed (default `C:\nwr`) |

Set them in the Administrator prompt you'll run everything from:

```cmd
set ARTIFACTORY_USER=first.last@trellix.com
set ARTIFACTORY_TOKEN=<artifactory token>
set XCLIENT_GITHUB_TOKEN=<github.trellix.com token>
set MA_SDK_FAKE_REPO=https://github.trellix.com/<owner>/ma-sdk-fake.git
```

Or set them once for your user account, then open a **new** Administrator prompt:

```cmd
setx ARTIFACTORY_USER "first.last@trellix.com"
setx ARTIFACTORY_TOKEN "<artifactory token>"
setx XCLIENT_GITHUB_TOKEN "<github.trellix.com token>"
setx MA_SDK_FAKE_REPO "https://github.trellix.com/<owner>/ma-sdk-fake.git"
```

## 3. Put the repo on the host

Copy or clone the repo into a folder without spaces, e.g. `C:\new_win_razor`. Then go to it in
the Administrator prompt:

```cmd
cd /d C:\new_win_razor
```

## 4. Install the prerequisites

```cmd
powershell -ExecutionPolicy Bypass -File setup.ps1
```

This installs into `C:\nwr`, with each tool installed only if it's missing:

- Python 3.9 and PortableGit;
- the repo's `venv\` (packages from `requirements.txt`);
- what the fake-MA XClient build needs: Visual Studio 2022 Build Tools (C++, MSVC 14.35,
  Windows SDK 10.0.22621), Windows Driver Kit, CMake 3.25.3, Strawberry Perl, Node.js 0.12.18,
  Conan 1.65 with the Trellix config, and WiX DTF.

The first run takes a long time (the Visual Studio Build Tools are large). At the end, the script
lists anything it couldn't install. Fix those problems and run it again until it reports none.
If Visual Studio asks for a reboot, reboot and run `setup.ps1` again.

**If you already have the XClient msi to test**, you only need Python, Git and the venv:

```cmd
powershell -ExecutionPolicy Bypass -File setup.ps1 -TestsOnly
```

## 5. Run the tests

From the repo folder, in the Administrator prompt with the variables from step 2 set, run one of
these.

**Test the latest passed XClient build** (the default):

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1
```

This command:

1. downloads the Orbit msi from Artifactory;
2. builds the fake-MA XClient from XClient's source at that build's commit and from
   `MA_SDK_FAKE_REPO` (it rebuilds only if a commit changed);
3. patches the fake `mxAgent.dll` into the msi;
4. installs the msi, provisions HXSim and runs every test;
5. uninstalls XClient at the end.

The first run's build takes an hour or more.

**Test a given version:**

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Version 50.4.0.174
```

**Test an msi you already have:**

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Msi C:\path\to\xclient.msi
```

**Test the Orbit msi with MA instead of the fake-MA msi:**

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -WithMA
```

**Run only some tests.** Give a comma-separated list of files or folders:

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Tests tests\test_audits\test_sysinfo.py
```

Only the Windows memory audit tests:

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Tests tests\test_audits\test_drivers_modulelist.py,tests\test_audits\test_drivers_signature.py,tests\test_audits\test_processes_api.py,tests\test_audits\test_processes_handle.py,tests\test_audits\test_processes_memory.py,tests\test_audits\test_processes_memoryacquire.py
```

To skip the IOC test that resets the network adapter (for example over RDP):

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Tests tests,-k,"not address_notification"
```

**Keep XClient installed between runs of the same msi:**

```cmd
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Msi <msi> -KeepInstalled
powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Cleanup
```

The second command uninstalls the kept install without running tests.

## 6. Check the results

- **Exit code:** `0` means all tests passed, `1` means at least one test failed, and `2` means
  the pre-flight checks refused to start (nothing was changed). The pre-flight checks look for
  things like a missing venv, an installed MA/XClient or a pending reboot.
- **Results folder:** `logs\<timestamp>_<label>\`, with:
  - `run.log`: the whole run;
  - `install.log`: the msi install;
  - `junit.xml`: the outcome of each test;
  - `pytest.log`: the detailed test log;
  - `results\`: each test's audit script and audit outputs.
- **Known failures:** they show up as `SKIPPED` with the reason `Known failure ...`.
- **After a run:** reboot the host if the uninstall left drivers to delete at boot.
  `run_tests.ps1` refuses to start while a reboot is pending.

To compare two runs (e.g. `-WithMA` against the fake-MA msi):

```cmd
venv\Scripts\python compare_results.py logs\<run A> logs\<run B> --out comparison.md
```

## 7. (Optional) Run it in GitHub Actions

1. Push the repo to a GitHub repository.
2. On the test host, in an Administrator prompt with the variables from step 2 set, run:

   ```cmd
   powershell -ExecutionPolicy Bypass -File setup_runner.ps1 -Token <token from Settings > Actions > Runners > New self-hosted runner>
   ```

   This registers a self-hosted runner labelled `new-win-razor` that runs as a service.
3. Add these repository secrets (Settings > Secrets and variables > Actions):
   - `ARTIFACTORY_USER`
   - `ARTIFACTORY_TOKEN`
   - `XCLIENT_GITHUB_TOKEN`
   - `MA_SDK_FAKE_REPO`
   - optionally `MA_SDK_FAKE_BRANCH`
4. You can also set these optional repository variables:
   - `XCLIENT_RELEASE` (default `50.4.0`)
   - `PUSH_TESTS_ENABLED=false`
   - `NIGHTLY_ENABLED=false`
   - `AUTO_REBOOT=false`
5. The workflow `.github/workflows/tests.yml` runs on pushes and pull requests to `main`, nightly,
   and on demand from Actions > XClient tests > Run workflow.
