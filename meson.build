project(
    'scikit-digital-health',
    'c',
    version: '0.11.2',
    license: 'MIT',
    meson_version: '>=0.63',
)

# https://mesonbuild.com/Python-module.html
py_mod = import('python')
py3 = py_mod.find_installation()
py3_dep = py3.dependency()

# Adding at project level causes many spurious -lgfortran flags.
add_languages('fortran', native: false)

# debugging printing
# add_project_arguments('-DDEBUG', language: 'c')

subdir('src/skdh')
