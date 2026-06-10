# Racing Simulator Telemetry Collection: Technical Implementation Guide

**The racing sim ecosystem offers mature telemetry access through two primary methods**: UDP network packets for cross-platform collection (including consoles) and memory-mapped files for ultra-low latency PC access. Open source tools with permissive licenses provide solid foundations, though the proprietary SimHub dominates with support for 80+ games. Building a multi-game Windows daemon requires careful architecture to handle heterogeneous data formats, variable update rates (10Hz to 360Hz), and game-specific quirks while maintaining performance.

This matters because centralizing telemetry collection from multiple racing games unlocks powerful applications—real-time dashboards, data analysis, motion platforms, and custom hardware integration—but requires navigating diverse protocols, undocumented APIs, and platform-specific constraints. The good news: the community has extensively documented these systems and built reusable components that dramatically reduce implementation complexity.

## F1 games provide the most documented telemetry system via UDP

The official EA F1 game series (F1 24, F1 23, F1 22, and earlier) offers comprehensive **UDP-based telemetry with official specifications** published by Codemasters/EA. This represents the gold standard for racing game telemetry documentation.

The system transmits **15 distinct packet types** at configurable rates, with most games defaulting to **port 20777**. Configuration happens through in-game menus: Settings → Telemetry Settings, where you enable UDP output, set the target IP address (127.0.0.1 for local applications), and configure send rate (20Hz recommended). Each packet shares a common 29-byte header containing packet format version, game version, packet type ID, session UID, and frame identifier—critical for correlating data across packet types.

The telemetry covers six primary domains. **Motion data (packet ID 0)** provides world position, velocity vectors, G-forces (lateral, longitudinal, vertical), and orientation (yaw, pitch, roll) for all 22 cars. **Car telemetry (ID 6)** delivers real-time vehicle data: speed (km/h), throttle/brake/steering inputs (normalized 0.0-1.0), gear position, engine RPM, DRS status, and crucially—**four-wheel tire temperatures and pressures** updated at your specified rate. **Motion Ex data (ID 13)**, introduced in F1 23, adds suspension physics with position/velocity/acceleration per wheel, individual wheel speeds, slip ratios, slip angles, and wheel forces in three axes.

**Car status packets (ID 7)** expose race-critical information: fuel mass and remaining laps, ERS energy store in joules, ERS deployment mode, engine power outputs (ICE and MGU-K in watts), tire compound and age, and DRS activation distance. F1 24 added **chassis yaw angles and front/rear aero heights** to the Motion Ex packet, enabling advanced aerodynamic analysis. The **damage packet (ID 10)**, updated at 10Hz in recent versions, tracks tire wear percentages, brake damage, wing damage, and engine component wear for MGU-H, MGU-K, ICE, and gearbox.

Version differences matter for compatibility. F1 24 introduced the **Time Trial packet (ID 14)** and expanded weather forecasts from 56 to 64 samples, while F1 23 added minute-precision sector times and overall frame identifiers that don't reset on flashback. Each game version maintains backward compatibility for the two previous formats, so an application built for F1 24 can handle F1 23 and F1 22 packets by checking the m_packetFormat field in headers.

Implementation requires **little-endian binary parsing of packed structures** (no padding between fields). The wheel array always follows the order: [0]=Rear Left, [1]=Rear Right, [2]=Front Left, [3]=Front Right. For normalized direction vectors, divide int16 values by 32767.0 to get float range -1.0 to 1.0. UDP being unreliable means implementing packet loss detection via frame identifiers and sequence numbers. Community implementations exist in **Python** (f1-24-telemetry, f1-23-telemetry), **TypeScript** (f1-telemetry-client supporting F1 18-25), **Rust** (f1-game-packet-parser), and **C#** (f1-sharp).

## Different racing games require fundamentally different collection methods

**Assetto Corsa Competizione** uses **three Windows memory-mapped files** for telemetry, not UDP. Opening `Local\acpmf_physics`, `Local\acpmf_graphics`, and `Local\acpmf_static` provides physics data at ~333Hz, graphics/session data at ~60Hz, and static configuration respectively. No in-game configuration needed—the shared memory becomes available automatically when ACC runs on Windows. This delivers **ultra-low latency** but restricts collection to the same PC (shared memory cannot cross network boundaries) and **console versions offer zero telemetry access**.

The physics buffer provides tire core/inner/outer temperatures, suspension travel per wheel, wheel slip ratios, brake temperatures, brake pad wear, and 3-axis G-forces updated 333 times per second—crucial for fine-grained analysis. The graphics buffer adds lap times, sector splits, car positions (up to 60 cars), weather data including wind speed/direction, and TC/ABS settings. Community libraries exist for C# (Thomsen.AccTools.SharedMemory NuGet package), Python (PyAccSharedMemory), Rust (acc_shared_memory_rs), and Go.

**Gran Turismo 7** takes a unique approach: **UDP with Salsa20 encryption**. The PS4/PS5 console game requires your application to send heartbeat packets (single character 'A', 'B', or '~') to the console's IP on **port 33740 every ~1.6 seconds** to activate the data stream. The console responds with encrypted 296/316/344-byte packets at 60Hz containing position, velocity, RPM, tire data, and lap information. 

Decryption uses **Salsa20 cipher with key "Simulator Interface Packet GT7 ver 0.0"** and an 8-byte nonce constructed from the packet's IV value XOR'd with magic constants (0xDEADBEAF for type A packets). The community reverse-engineered this entirely—Sony provides no official documentation. Python implementations like gt7dashboard and gt7telemetry handle encryption and provide working examples. Packet B adds 5 floats for wheel rotation/acceleration, while Packet ~ includes full data but isn't available in Sport Mode or replays.

**Forza Motorsport** (2023 and earlier versions) offers **unencrypted UDP** with two formats. Enable via HUD Options → Data Out, set target IP (localhost support added in FM 2023), port (default 9999), and choose format. The **Dash format** (311 bytes, 60Hz) provides comprehensive data: engine stats, tire slip per wheel, tire/brake temperatures, suspension travel, boost, fuel, position, lap distance, and car class information. The simpler Sled format (232 bytes) focuses on motion platform data. Official documentation exists at support.forzamotorsport.net with full packet byte layouts. The critical limitation: **only one application can listen on a UDP port**, requiring port forwarding for multi-app scenarios.

**iRacing** provides the most sophisticated system via its **official SDK using shared memory**. Opening the memory-mapped file `Local\IRSDKMemMapFileName` grants access to 300+ telemetry variables at 60Hz (configurable to 360Hz via `irsdkLog360Hz=1` in app.ini). The header structure describes variable offsets and types, with session info in YAML format and live telemetry in binary structs. iRacing also saves .ibt binary files automatically to Documents\iRacing\telemetry for offline analysis. The pyirsdk library (MIT license) provides the standard Python implementation, while node-irsdk serves JavaScript developers.

| Game | Method | Platform | Rate | Port/Name | Encryption |
|------|--------|----------|------|-----------|------------|
| F1 24/23 | UDP | PC/Console | 20-60Hz | 20777 | None |
| ACC | Shared Memory | PC only | Physics: 333Hz | Local\acpmf_* | None |
| GT7 | UDP | PS4/PS5 | 60Hz | 33740 | Salsa20 |
| Forza Motorsport | UDP | PC/Xbox | 60Hz | 9999 | None |
| iRacing | Shared Memory + SDK | PC only | 60-360Hz | Local\IRSDK* | None |

The implementation takeaway: **UDP enables cross-platform collection including consoles but accepts potential packet loss**, while **shared memory delivers rock-solid performance at 333Hz but locks you to Windows PCs**. Your architecture must support both to cover the major racing sims comprehensively.

## Python offers mature open source libraries with permissive licenses

**FastF1 (MIT license)** stands out as the most polished Python telemetry library, though it targets real Formula 1 timing data rather than game telemetry. With 1,674+ GitHub stars and active maintenance (version 3.6.1), it provides pandas DataFrames for F1 lap timing, car telemetry, position data, and weather from 2018 onwards. The API design demonstrates best practices for telemetry data structures: `session = fastf1.get_session(2024, 'Monza', 'Q'); session.load(); fastest_lap = session.laps.pick_fastest(); telemetry = fastest_lap.get_car_data()`. While not applicable for game data collection, FastF1's architecture offers excellent reference patterns for building similar systems.

For F1 games specifically, **f1-telemetry by P403n1x87 (MIT license)** provides production-ready UDP packet collection for F1 2018-2025+. Version 2025.3.3 was released in July 2025, demonstrating active maintenance. The tool collects telemetry via UDP, integrates with InfluxDB for time-series storage, includes a web visualization frontend, and can run without database backing for pure streaming. Installation via `pipx install f1-telemetry` provides a standalone `f1-tel` command. The companion **f1-packets library (MIT, version 2025.1.1)** handles packet parsing as a reusable component, separating concerns between network reception and protocol parsing—valuable architecture for custom implementations.

**pyirsdk** delivers the standard Python interface for iRacing's SDK. Requiring Python 3.7+ and PyYAML 5.3+, it wraps the iRacing shared memory API with simple property access: `ir = irsdk.IRSDK(); ir.startup(); print(ir['Speed'])`. The library handles memory-mapped file reading, YAML session parsing, and telemetry variable lookup, removing low-level implementation burden. Community adoption makes this the de facto standard for Python-based iRacing tools.

**Game-specific parsers** exist for older F1 versions but show varying maintenance. f1-2020-telemetry (MIT, version 0.2.1) documented on ReadTheDocs provides command-line tools for recording, playback, and monitoring F1 2020 data. f1-23-telemetry (MIT, by Chris Hannam) covers F1 23. However, pytelemetry for F1 2018 shows signs of abandonment with no clear license file and last activity circa 2018—highlighting the ecosystem's fragmentation across game versions.

**Multi-game telemetry frameworks with permissive licenses remain rare**. RacingGameTelemetry uses LGPL 2.1 (less permissive than MIT) and supports DiRT 3/Rally/4 plus F1 2015-2017 but shows limited recent activity. TinyPedal for rFactor 2/Le Mans Ultimate uses GPL v3 (copyleft, not permissive) despite being actively maintained. The gap: no mature, MIT/Apache-licensed library provides unified access to multiple racing games—this represents an **open opportunity for new open source projects**.

Beyond Python, **f1-telemetry-client (TypeScript, MIT)** provides Node.js access to F1 18-25 games with comprehensive format support. Forza-data-tools (Go) offers realtime output, CSV logging, and JSON-over-HTTP for Forza Motorsport 7 and Horizon 4, though licensing remains unclear. The ecosystem demonstrates strong per-game libraries but weak cross-game abstraction layers.

## SimHub dominates as the universal telemetry hub but isn't a library

**SimHub by Wotever is proprietary freeware** with optional paid licensing (€6+ suggested donation). The critical finding for developers: **SimHub cannot be embedded as a library**—it's a standalone Windows application with no SDK for external integration, no C/C++/Python bindings, and no API to add new games. You must run the full GUI application (can minimize to tray) and integrate through specific extension points.

That said, SimHub supports **80+ racing and flight simulators** including iRacing, ACC, Assetto Corsa EVO, rFactor 2, Le Mans Ultimate, F1 2016-2025, Forza Motorsport/Horizon, Gran Turismo 7, Project CARS, Automobilista, DiRT Rally series, BeamNG, Euro Truck Simulator 2, Microsoft Flight Simulator, X-Plane, and DCS World. This comprehensive coverage results from eight years of development by a single highly-responsive developer who continuously adds games (recent additions: Wreckfest 2, Flight Sim 2024, F1 25).

SimHub's **telemetry collection methods** match the patterns described earlier: shared memory for ACC/rFactor 2/Project CARS 2, UDP for F1/Forza/console games, memory reading via XML pointer files for games without native telemetry (Elite Dangerous), and plugin-based integration for others (BeamNG, ETS2/ATS). The architecture centralizes game readers in the core application—**community plugins cannot add new game support**, only extend functionality of existing games.

**Four integration approaches exist** for developers who want to use SimHub:

The **C# plugin SDK** lets you create plugins that run inside SimHub's process. Implementing `IDataPlugin` and `IWPFSettings` interfaces grants access to the central `GameData` structure updated at configured refresh rates. Plugins can create custom properties (`pluginManager.AddProperty("MyPlugin.MyProperty", value)`), add actions, and build WPF settings UI. Demo projects exist in the GitHub wiki, though documentation remains sparse. The limitation: plugins require C#/.NET Framework 4.8, can only extend existing games, and undocumented APIs may break without warning.

**UDP forwarding** allows SimHub to receive telemetry on one port (e.g., 20777 from F1 2023) and forward to your custom application on another port (e.g., 20888). This works cleanly for UDP-based games but **cannot forward shared memory games** without additional plugins. The pattern: let SimHub handle game compatibility, consume its forwarded UDP stream in your application.

**Custom serial protocols** enable text-based communication with Arduino and microcontrollers. SimHub sends formatted telemetry strings over serial ports to custom hardware. The **REST API** exists but remains limited to motion control, not general telemetry access.

The **free version operates at ~10Hz telemetry refresh**, while the **paid license (€6+ one-time donation) unlocks 60Hz** updates, sharper bass shaker effects, and priority support. The separate **Motion Addon license** enables 2DOF/3DOF/6DOF motion platform features. GitHub (929 stars, 102 forks) hosts documentation and issue tracking but not source code—it's proprietary.

SimHub's **limitations for custom development** include: not usable as library, no Linux/macOS support (Windows only), single developer dependency, cannot add games without core updates, C# plugin-only (no other languages), and limited external data API. The workaround architecture: run SimHub on a dedicated PC or as a dependency, develop C# plugins for internal features, use UDP forwarding for external applications, and accept the proprietary nature.

The **community ecosystem** remains massive with over 12,000 Discord members, thousands of custom dashboards on RaceDepartment/OverTake, and active plugin development. Popular plugins include EasyScript (NCalc/JavaScript property creation via UI), UDPConnector (generic UDP ingestion), and various hardware-specific extensions. SimHub works alongside complementary tools like CrewChief (voice race engineer), Lovely Dashboard (premium dashboard system), and Track Titan (telemetry analysis) through UDP forwarding.

## Building a Windows daemon requires handling two fundamentally different protocols

Modern **.NET (Core 3.1+, .NET 5/6+) provides BackgroundService** as the foundation for Windows services. Implementing the abstract class with `protected override async Task ExecuteAsync(CancellationToken stoppingToken)` creates a long-running service. The `Host.CreateDefaultBuilder(args).UseWindowsService()` call enables Windows Service mode while maintaining console mode for development. Deploy via `sc.exe create "Racing Telemetry Service" binPath="C:\Path\To\Service.exe"`.

**UDP reception** uses `UdpClient` from System.Net.Sockets. Bind to `IPEndPoint(IPAddress.Any, port)` to receive on all network interfaces, then call `await _udpClient.ReceiveAsync()` in a loop. Key considerations: UDP is unreliable (accept occasional packet loss for real-time applications), only one application can bind to a port (enable ReuseAddress socket option for multiple receivers), implement sequence number tracking to detect gaps, and log loss rates for monitoring. The typical pattern: separate collection thread receiving UDP packets at 60Hz, channel or queue to processing thread, batch processing for database writes to avoid I/O bottlenecks.

**Shared memory reading** requires `System.IO.MemoryMappedFiles`. Open via `MemoryMappedFile.OpenExisting("Local\\IRSDKMemMapFileName")`, create a `MemoryMappedViewAccessor`, then read binary structures at offsets: `accessor.Read<T>(offset, out data)`. The **critical challenge: avoiding partially-updated data** during concurrent writes. Solutions include reading sequence numbers before and after the data read (retry if mismatched), using double buffering when game supports it, and ring buffers with tick counts for synchronization (iRacing's approach).

**Multi-game architecture** demands three layers. The **detection layer** polls running processes every 2 seconds via `Process.GetProcesses()` and matches against game profiles (JSON/YAML config: process name, telemetry type, port/memory map name). More sophisticated implementations use WMI `Win32_ProcessStartTrace` events for instant detection. The **abstraction layer** defines `interface ITelemetryReader` with `Start()`, `Stop()`, and `event EventHandler<TelemetryDataEventArgs> DataReceived`, implemented by `UdpTelemetryReader` and `SharedMemoryTelemetryReader` concrete classes. A factory creates readers based on detected game profiles. The **normalization layer** maps heterogeneous game formats to a unified `NormalizedTelemetry` structure.

```csharp
public class NormalizedTelemetry
{
    public float Speed { get; set; }  // m/s standardized
    public int Gear { get; set; }
    public float EngineRpm { get; set; }
    public float Throttle { get; set; }  // 0.0-1.0 normalized
    public float Brake { get; set; }
    public float Steering { get; set; }  // -1.0 to 1.0
    public WheelData[] Wheels { get; set; }  // [FL, FR, RL, RR]
    public Vector3 Position { get; set; }
    public string GameName { get; set; }
    public DateTime Timestamp { get; set; }
}
```

**Game-specific parsers** implement `interface ITelemetryParser { NormalizedTelemetry Parse(byte[] rawData); }`, handling F1's multi-packet correlation, iRacing's YAML session info separation, ACC's three memory regions, and Forza's two formats. Unit conversions become mandatory: m/s to km/h (multiply by 3.6), Celsius to Fahrenheit (×9/5 + 32), bar to PSI (×14.5), degrees to radians (×π/180).

**Performance optimization** matters at 60-360Hz update rates. Use `System.Threading.Channels` for lock-free producer/consumer patterns, `ArrayPool<T>` for frequent allocations, batch database writes (collect 100 samples, write once), and separate threads for collection vs processing. Memory pooling reduces garbage collection pressure: `var buffer = ArrayPool<byte>.Shared.Rent(2048); try { /* use */ } finally { ArrayPool<byte>.Shared.Return(buffer); }`.

**Common technical challenges** include correlating F1's 15 packet types (track frame identifiers), handling iRacing's 300+ variables in binary format, GT7's encryption requirement, ACC's three separate memory maps (physics/graphics/static), and variable update rates per game (adaptive sampling based on timestamps). Port conflicts require detection and graceful error messages. Windows Store/Game Pass games often block telemetry, requiring AppContainer Loopback Utility workarounds.

## Critical implementation decisions determine success

**Starting point architecture**: Begin with single-game support (F1 recommended due to documentation quality), implement UDP reception and packet parsing, validate data accuracy against in-game displays, then expand to second game with shared memory (iRacing or ACC) to prove dual-protocol handling. The abstraction layer must exist from day one—retrofitting clean interfaces after implementing game-specific code creates technical debt.

**Data normalization philosophy**: Normalize to SI units (m/s for speed, Celsius for temperature, meters for distance) in your unified model, then convert to display units only at presentation layer. This ensures calculations work consistently regardless of source game. Store both raw game data and normalized data for debugging—compressed binary formats (MessagePack, Protocol Buffers) keep storage manageable at 60Hz rates.

**Error handling strategy**: Accept that UDP packets will occasionally drop—**telemetry is fundamentally best-effort**. Track packet loss percentage (acceptable: \u003c1%), log gaps, but don't retry or request retransmits (impossible with UDP). For shared memory, implement retry logic with sequence number checking. Games crash, disconnect, or get minimized—detect via process monitoring and gracefully suspend collection without crashing the daemon.

**Configuration management**: External JSON/YAML game profiles prevent recompilation for new games. Schema: `{ "name": "F1 2023", "processName": "F1_23", "telemetryType": "udp", "port": 20777, "packetFormat": "f1_2023", "updateRate": 60 }`. Support hot-reload to add games without service restart. Version detection matters—F1 24 differs from F1 23 in packet structures, requiring format selection based on m_packetFormat header field.

**Testing approach**: Record actual game UDP streams to binary files during development (`File.WriteAllBytes($"capture_{timestamp}.bin", packetBuffer)`), then replay for unit testing without running games. Mock the `ITelemetryReader` interface for testing normalization logic. Performance testing requires sustained 60Hz load for 30+ minutes to catch memory leaks or CPU spikes.

**Deployment considerations**: Install as Windows Service for production (automatic start on boot, runs without user login), but support console mode for development. Use .NET Worker Service template which provides both modes via `UseWindowsService()`. Implement health monitoring endpoints (HTTP on localhost:5000) showing connected game, packet rate, memory usage, and uptime. Create MSI installer for easy deployment or use ClickOnce for auto-updates.

## Standards and interoperability remain limited

The racing sim ecosystem **lacks universal telemetry standards**—each game implements bespoke formats. iRacing uses custom binary structs with YAML metadata. F1 games have evolved through multiple packet format versions (2018, 2019, 2020, 2021, 2022, 2023, 2024). ACC inherited Kunos Simulazioni's shared memory design from Assetto Corsa but with structure modifications. GT7 created entirely custom encrypted UDP. This fragmentation **forces multi-game tools to implement per-game parsers**.

**Attempts at standardization remain minimal**. OpenSimTools proposed unified APIs but gained little traction. The closest to de facto standards: **OutGauge protocol** (originally from Live for Speed, adopted by BeamNG and others) for basic dash data, and **SimHub's position as integration hub** despite being proprietary. Most games prioritize their own use cases over interoperability.

**Data format patterns** do show commonalities worth leveraging:
- **Little-endian binary** predominates on PC (Intel/AMD x86-64)
- **Packed structs** without padding common for network efficiency  
- **Header + payload** structure universal (version, packet type, sequence, data)
- **Separate packets** for static vs dynamic data (iRacing session YAML, F1 participants packet)
- **Per-wheel arrays** consistently use [FL, FR, RL, RR] or [RL, RR, FL, FR] ordering

**Converting to analysis formats**: MoTeC i2 Pro (free telemetry analysis software) has become the target format for many converters. Tools exist for iRacing (.ibt to MoTeC via Mu converter), Gran Turismo (GeekyDeaks/sim-to-motec), and others. If building a custom system, **supporting MoTeC export** provides immediate compatibility with professional analysis tools.

**Cross-platform considerations**: UDP enables console telemetry (GT7 on PS5, Forza on Xbox), but shared memory remains Windows-exclusive. Linux users of ACC via Proton/Wine cannot access shared memory—requiring wine-compatible alternatives or UDP relays. macOS has minimal racing sim presence, reducing priority. Mobile dashboards (tablets, phones) receive UDP over WiFi—latency acceptable for dash display, less so for motion platforms.

**Future-proofing strategy**: Version detection in packet headers, configuration-driven game profiles, plugin architecture for custom parsers, and comprehensive logging of unknown packet types. When F1 25 launches with new packet structures, your system should detect format 2025, log warnings about unknown packets, and continue processing compatible fields while awaiting parser updates.

## Conclusion: The path forward for custom telemetry systems

Racing simulator telemetry collection in 2025 offers mature technical foundations through official specifications (F1 games), well-documented SDKs (iRacing), and extensive community reverse-engineering (Gran Turismo, ACC). The **dual protocol architecture—UDP for cross-platform flexibility plus shared memory for PC performance—covers virtually all major racing sims**. Open source libraries like f1-telemetry, pyirsdk, and f1-packets provide permissive-licensed building blocks, though multi-game frameworks remain surprisingly absent.

**Three viable implementation approaches exist**. First, **leverage SimHub as dependency**: run it for 80+ game support, develop C# plugins for custom features, forward UDP to your applications—trading architectural control for breadth. Second, **build custom daemon from scratch**: .NET BackgroundService with UDP and shared memory readers, per-game parsers, unified data model—maximum flexibility but significant maintenance burden as games update. Third, **hybrid approach**: use game-specific open source libraries (pyirsdk for iRacing, f1-telemetry for F1) wrapped in your abstraction layer, adding only the games you need.

The **technical challenges—heterogeneous formats, variable update rates, unreliable UDP, game-specific quirks—have known solutions** documented in this report: interface-based abstraction, sequence number tracking, adaptive sampling, normalization layers, and configuration-driven game profiles. Performance at 60-360Hz demands System.Threading.Channels for lock-free queuing, memory pooling to reduce GC pressure, and separation of collection from processing threads.

Start with single-game implementation to prove architecture, expand systematically with shared memory support, implement comprehensive logging from day one, and design for extensibility knowing racing sims will continue fragmenting their formats. The ecosystem's maturity combined with documented protocols makes custom telemetry collection tractable for developers willing to handle multiple protocols and embrace game-specific complexity.