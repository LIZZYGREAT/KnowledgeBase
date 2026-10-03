export type NavigationGuard = () => Promise<boolean>;
export type RegisterBeforeNavigate = (guard: NavigationGuard) => () => void;

export async function navigateWithGuards(
  path: string,
  guards: Iterable<NavigationGuard>,
  navigate: (path: string) => void,
): Promise<boolean> {
  for (const guard of guards) {
    if (!await guard()) return false;
  }
  navigate(path);
  return true;
}
