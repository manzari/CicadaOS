# micropython.cmake -- build glue for the ced25519 native module.
#
# Point MicroPython's USER_C_MODULES at this file. It compiles the wrapper
# together with the two Monocypher source files you drop into this directory.

add_library(usermod_ced25519 INTERFACE)

target_sources(usermod_ced25519 INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/moned25519.c
    ${CMAKE_CURRENT_LIST_DIR}/monocypher.c
    ${CMAKE_CURRENT_LIST_DIR}/monocypher-ed25519.c
)

target_include_directories(usermod_ced25519 INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod INTERFACE usermod_ced25519)
