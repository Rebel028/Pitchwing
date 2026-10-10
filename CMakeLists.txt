cmake_minimum_required(VERSION 3.20)
project(Pitchwing VERSION 0.1.0 LANGUAGES CXX)

# All dependencies are checked in. Configuration never downloads packages.
set(pitchwing_top_level OFF)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    set(pitchwing_top_level ON)
    # Do not create or change a parent project's BUILD_TESTING option.
    include(CTest)
endif()
set(pitchwing_tests_default OFF)
if(pitchwing_top_level AND BUILD_TESTING)
    set(pitchwing_tests_default ON)
endif()
option(PITCHWING_BUILD_TOOLS "Build Pitchwing offline tools" ${pitchwing_top_level})
option(PITCHWING_BUILD_TESTS "Build Pitchwing contract tests" ${pitchwing_tests_default})
option(PITCHWING_ENABLE_ASAN "Enable AddressSanitizer for native targets" OFF)
option(PITCHWING_ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer for native targets" OFF)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

if((PITCHWING_ENABLE_ASAN OR PITCHWING_ENABLE_UBSAN)
   AND NOT CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    message(FATAL_ERROR "The sanitizer options currently require GCC or Clang")
endif()

set(pitchwing_sanitizers "")
if(PITCHWING_ENABLE_ASAN)
    list(APPEND pitchwing_sanitizers address)
endif()
if(PITCHWING_ENABLE_UBSAN)
    list(APPEND pitchwing_sanitizers undefined)
endif()
list(JOIN pitchwing_sanitizers "," pitchwing_sanitizer_list)

function(pitchwing_configure_target target)
    target_compile_features(${target} PUBLIC cxx_std_17)
    set_target_properties(${target} PROPERTIES CXX_EXTENSIONS OFF)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4)
    elseif(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    if(pitchwing_sanitizer_list)
        target_compile_options(${target} PRIVATE
            -fsanitize=${pitchwing_sanitizer_list} -fno-sanitize-recover=all
            -fno-omit-frame-pointer)
        # PUBLIC also supplies the sanitizer runtime when a consumer links the
        # instrumented static library. No runtime flags leak into normal builds.
        target_link_options(${target} PUBLIC -fsanitize=${pitchwing_sanitizer_list})
    endif()
endfunction()

add_library(pitchwing STATIC src/Engine.cpp src/LiveEngine.cpp)
add_library(pitchwing::pitchwing ALIAS pitchwing)
set_target_properties(pitchwing PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(pitchwing PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_include_directories(pitchwing SYSTEM PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/third_party")
pitchwing_configure_target(pitchwing)

if(PITCHWING_BUILD_TOOLS)
    add_executable(pitchwing_render tools/pitchwing_render.cpp)
    target_link_libraries(pitchwing_render PRIVATE pitchwing::pitchwing)
    pitchwing_configure_target(pitchwing_render)

    add_executable(pitchwing_live_probe tools/pitchwing_live_probe.cpp)
    target_link_libraries(pitchwing_live_probe PRIVATE pitchwing::pitchwing)
    pitchwing_configure_target(pitchwing_live_probe)

    add_executable(pitchwing_live_render tools/pitchwing_live_render.cpp)
    target_link_libraries(pitchwing_live_render PRIVATE pitchwing::pitchwing)
    pitchwing_configure_target(pitchwing_live_render)
endif()

# A parent's explicit BUILD_TESTING=OFF wins. An embedding project that enables
# these tests should also call enable_testing() at its own top level.
if(PITCHWING_BUILD_TESTS AND (NOT DEFINED BUILD_TESTING OR BUILD_TESTING))
    enable_testing()
    add_executable(pitchwing_tests tests/engine_tests.cpp)
    target_link_libraries(pitchwing_tests PRIVATE pitchwing::pitchwing)
    pitchwing_configure_target(pitchwing_tests)
    add_test(NAME pitchwing_engine COMMAND pitchwing_tests)
    set_tests_properties(pitchwing_engine PROPERTIES LABELS "engine;contract")

    add_executable(pitchwing_live_tests tests/live_engine_tests.cpp)
    target_link_libraries(pitchwing_live_tests PRIVATE pitchwing::pitchwing)
    pitchwing_configure_target(pitchwing_live_tests)
    add_test(NAME pitchwing_live_engine COMMAND pitchwing_live_tests)
    set_tests_properties(pitchwing_live_engine PROPERTIES LABELS "engine;live;contract")
endif()

set(pitchwing_package_dir "${CMAKE_INSTALL_LIBDIR}/cmake/pitchwing")
configure_package_config_file(cmake/pitchwingConfig.cmake.in
    "${CMAKE_CURRENT_BINARY_DIR}/pitchwingConfig.cmake"
    INSTALL_DESTINATION "${pitchwing_package_dir}")
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/pitchwingConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMinorVersion)

install(TARGETS pitchwing EXPORT pitchwingTargets
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}")
install(DIRECTORY include/pitchwing DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    FILES_MATCHING PATTERN "*.hpp")
install(EXPORT pitchwingTargets FILE pitchwingTargets.cmake
    NAMESPACE pitchwing:: DESTINATION "${pitchwing_package_dir}")
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/pitchwingConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/pitchwingConfigVersion.cmake"
    DESTINATION "${pitchwing_package_dir}")
install(FILES third_party/signalsmith-linear/LICENSE.txt
    DESTINATION "${CMAKE_INSTALL_DATADIR}/pitchwing/licenses/signalsmith-linear")
